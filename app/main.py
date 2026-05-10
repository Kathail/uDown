import asyncio
import logging
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import AsyncIterator

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from app.auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    make_session_cookie,
    require_session,
    verify_password,
    verify_session_cookie,
)
from app.pipeline import download_as_mp3
from app.resolver import ResolveError, VideoEntry, resolve
from app.zipstream import sanitize_filename, stream_zip

log = logging.getLogger("udown")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

# Indirected for monkeypatching in tests.
PIPELINE = download_as_mp3

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Concurrency cap. Created lazily so tests can change the env var first.
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        cap = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", "2"))
        _semaphore = asyncio.Semaphore(cap)
    return _semaphore


# Resolve cache: {(session_token, url): (timestamp, entries)}.
_RESOLVE_CACHE: dict[tuple[str, str], tuple[float, list[VideoEntry]]] = {}
_RESOLVE_CACHE_TTL = 60  # seconds


def _cache_key(session: str, url: str) -> tuple[str, str]:
    return (session, url)


def _cache_get(session: str, url: str) -> list[VideoEntry] | None:
    key = _cache_key(session, url)
    hit = _RESOLVE_CACHE.get(key)
    if hit is None:
        return None
    ts, entries = hit
    if time.time() - ts > _RESOLVE_CACHE_TTL:
        _RESOLVE_CACHE.pop(key, None)
        return None
    return entries


def _cache_put(session: str, url: str, entries: list[VideoEntry]) -> None:
    _RESOLVE_CACHE[_cache_key(session, url)] = (time.time(), entries)


# ---- routes --------------------------------------------------------------


@app.on_event("startup")
async def startup() -> None:
    # Validate env vars by reading them.
    if not os.environ.get("APP_PASSWORD"):
        raise RuntimeError("APP_PASSWORD env var is required")
    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("SESSION_SECRET env var must be at least 32 chars")

    # ffmpeg probe — log a warning but don't crash if missing in dev.
    if os.environ.get("UDOWN_REQUIRE_FFMPEG", "1") == "1":
        import shutil

        if shutil.which("ffmpeg") is None:
            log.warning("ffmpeg not found on PATH — downloads will fail")


@app.get("/", response_class=HTMLResponse)
async def index() -> Response:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/me")
async def me(udown_session: str | None = Cookie(default=None)) -> Response:
    if not verify_session_cookie(udown_session or ""):
        raise HTTPException(status_code=401, detail="not authenticated")
    return JSONResponse({"ok": True})


@app.post("/login")
async def login(password: str = Form(...)) -> Response:
    if not verify_password(password):
        raise HTTPException(status_code=401, detail="incorrect password")
    cookie = make_session_cookie()
    secure = os.environ.get("UDOWN_COOKIE_SECURE", "0") == "1"
    response = JSONResponse({"ok": True})
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=secure,
    )
    return response


@app.post("/logout")
async def logout() -> Response:
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.post("/download/preflight")
async def preflight(
    request: Request,
    udown_session: str | None = Cookie(default=None),
    _: None = Depends(require_session),
) -> Response:
    # require_session has already 401'd on a missing cookie.
    assert udown_session is not None
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    try:
        entries = resolve(url)
    except ResolveError as e:
        log.info("preflight failed: url=%r reason=%s", url, e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    _cache_put(udown_session, url, entries)
    title = entries[0].title if len(entries) == 1 else "playlist"
    log.info("preflight ok: url=%r entry_count=%d", url, len(entries))
    return JSONResponse({
        "entry_count": len(entries),
        "suggested_filename": sanitize_filename(title) + ".zip",
    })


@app.post("/download")
async def download(
    url: str = Form(...),
    udown_session: str | None = Cookie(default=None),
    _: None = Depends(require_session),
) -> Response:
    assert udown_session is not None
    sem = _get_semaphore()
    wait = float(os.environ.get("SEMAPHORE_WAIT_SECONDS", "30"))
    try:
        await asyncio.wait_for(sem.acquire(), timeout=wait)
    except asyncio.TimeoutError:
        log.warning("download 503: semaphore exhausted url=%r", url)
        raise HTTPException(status_code=503, detail="server busy, retry shortly")

    entries = _cache_get(udown_session, url)
    if entries is None:
        try:
            entries = resolve(url)
        except ResolveError as e:
            sem.release()
            log.info("download 400: url=%r reason=%s", url, e)
            raise HTTPException(status_code=400, detail=str(e)) from e

    suggested = (
        sanitize_filename(entries[0].title) if len(entries) == 1 else "playlist"
    )
    ascii_fallback = re.sub(r"[^A-Za-z0-9._-]", "_", suggested) or "download"
    encoded = urllib.parse.quote(suggested, safe="")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_fallback}.zip"; '
            f"filename*=UTF-8''{encoded}.zip"
        )
    }

    started = time.time()
    log.info("download start: url=%r entry_count=%d", url, len(entries))

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in stream_zip(entries, pipeline=PIPELINE):
                yield chunk
            duration_ms = int((time.time() - started) * 1000)
            log.info("download done: url=%r duration_ms=%d", url, duration_ms)
        except asyncio.CancelledError:
            duration_ms = int((time.time() - started) * 1000)
            log.info("download canceled: url=%r duration_ms=%d", url, duration_ms)
            raise
        finally:
            sem.release()

    return StreamingResponse(body(), media_type="application/zip", headers=headers)
