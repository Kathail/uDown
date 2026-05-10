import asyncio
import io
import zipfile
from typing import AsyncIterator

import httpx
import pytest
from httpx import ASGITransport

from app.resolver import VideoEntry


@pytest.fixture
def fake_resolve(monkeypatch):
    """Replace resolver.resolve with a callable returning configurable entries."""
    state = {"entries": [VideoEntry(id="x", webpage_url="https://youtube.com/watch?v=x", title="T")], "raises": None}

    def _fake(url: str):
        if state["raises"]:
            raise state["raises"]
        return list(state["entries"])

    import app.main as m
    # Clear the resolve cache so stale entries from other tests don't interfere.
    m._RESOLVE_CACHE.clear()
    monkeypatch.setattr(m, "resolve", _fake)
    return state


@pytest.fixture
def fake_pipeline(monkeypatch):
    """Replace the pipeline used by stream_zip with a deterministic fake."""

    async def _fake(entry: VideoEntry) -> AsyncIterator[bytes]:
        yield f"audio-of-{entry.id}".encode()

    import app.main as m
    monkeypatch.setattr(m, "PIPELINE", _fake)
    return _fake


@pytest.fixture
async def client():
    from app.main import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---- auth ----------------------------------------------------------------


async def test_login_required_for_download(client):
    r = await client.post("/download", data={"url": "https://youtube.com/watch?v=x"})
    assert r.status_code == 401


async def test_login_correct_password_sets_cookie(client):
    r = await client.post("/login", data={"password": "test-password"})
    assert r.status_code in (200, 303)
    assert "udown_session" in r.cookies


async def test_login_wrong_password_returns_401(client):
    r = await client.post("/login", data={"password": "wrong"})
    assert r.status_code == 401


async def _login(client):
    await client.post("/login", data={"password": "test-password"})


# ---- preflight -----------------------------------------------------------


async def test_preflight_returns_entry_count(client, fake_resolve):
    await _login(client)
    fake_resolve["entries"] = [
        VideoEntry(id=str(i), webpage_url=f"https://youtube.com/watch?v={i}", title=f"t{i}")
        for i in range(3)
    ]
    r = await client.post("/download/preflight", json={"url": "https://youtube.com/playlist?list=PL"})
    assert r.status_code == 200
    assert r.json()["entry_count"] == 3


async def test_preflight_invalid_url_returns_400(client, fake_resolve):
    from app.resolver import ResolveError

    await _login(client)
    fake_resolve["raises"] = ResolveError("bad URL")
    r = await client.post("/download/preflight", json={"url": "bogus"})
    assert r.status_code == 400


# ---- download ------------------------------------------------------------


async def test_download_streams_zip(client, fake_resolve, fake_pipeline):
    await _login(client)
    fake_resolve["entries"] = [
        VideoEntry(id="a", webpage_url="https://youtube.com/watch?v=a", title="A"),
        VideoEntry(id="b", webpage_url="https://youtube.com/watch?v=b", title="B"),
    ]
    r = await client.post("/download", data={"url": "https://youtube.com/playlist?list=PL"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(zf.namelist()) == ["A.mp3", "B.mp3"]


async def test_download_uses_cached_resolve_after_preflight(client, fake_resolve, fake_pipeline):
    await _login(client)
    calls = []

    import app.main as m
    real = m.resolve

    def counting(url):
        calls.append(url)
        return real(url)

    m.resolve = counting
    try:
        await client.post("/download/preflight", json={"url": "https://youtube.com/watch?v=x"})
        r = await client.post("/download", data={"url": "https://youtube.com/watch?v=x"})
        assert r.status_code == 200
    finally:
        m.resolve = real

    # Preflight calls resolve once; /download should use the cache.
    assert len(calls) == 1


async def test_download_invalid_url_returns_400(client, fake_resolve):
    from app.resolver import ResolveError

    await _login(client)
    fake_resolve["raises"] = ResolveError("bad URL")
    r = await client.post("/download", data={"url": "bogus"})
    assert r.status_code == 400


async def test_resolve_cache_evicted_after_ttl(client, fake_resolve, fake_pipeline, monkeypatch):
    """After the TTL expires, /download must call resolve again."""
    import app.main as m

    await _login(client)
    calls = []
    real = m.resolve

    def counting(url):
        calls.append(url)
        return real(url)

    m.resolve = counting
    try:
        # Preflight populates cache.
        await client.post("/download/preflight", json={"url": "https://youtube.com/watch?v=x"})
        assert len(calls) == 1

        # Travel past the TTL.
        original_time = m.time.time
        monkeypatch.setattr(m.time, "time", lambda: original_time() + m._RESOLVE_CACHE_TTL + 1)

        r = await client.post("/download", data={"url": "https://youtube.com/watch?v=x"})
        assert r.status_code == 200
    finally:
        m.resolve = real

    # /download had to resolve again because the cache entry expired.
    assert len(calls) == 2


# ---- /me -----------------------------------------------------------------


async def test_me_unauthenticated(client):
    r = await client.get("/me")
    assert r.status_code == 401


async def test_me_authenticated(client):
    await _login(client)
    r = await client.get("/me")
    assert r.status_code == 200
