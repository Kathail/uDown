# uDown — Design Spec

**Date:** 2026-05-09
**Status:** Draft, awaiting user review

## 1. Summary

A small, password-gated web app that turns a YouTube URL into an MP3 download. Single videos and playlists are both supported. Personal-scale: one operator and a handful of trusted friends. Hosted on Railway (or any Docker host); also runnable locally.

The download is delivered as a **streaming zip** — the browser's native download UI fills in real time as the server transcodes one track at a time. There is no server-side job model, no DB, and no background worker.

## 2. Goals & non-goals

### Goals
- Paste a YouTube URL → get MP3(s) at 320 kbps via a normal browser download.
- Single videos and playlists both work through the same flow.
- Trivially deployable: one Docker image, no external services.
- Low operational burden: no DB, no Redis, no message queue.

### Non-goals (explicitly out of v1)
- Per-track progress UI beyond what the browser's native download bar shows.
- Resume of partial downloads (connection drop = restart the playlist).
- Embedding ID3 tags or thumbnail cover art.
- Recent-downloads history.
- Bypassing DRM, age gates, or YouTube's anti-bot challenges beyond an optional cookies file.
- Recording live streams or upcoming premieres.
- Per-user accounts (single shared password is the gate).
- Public scale / open access (single shared password assumes a small trusted group).

## 3. User flow

1. User opens the site, sees a login form.
2. Enters the shared password → server sets a 30-day signed session cookie.
3. Pastes a YouTube URL into the form, hits Submit.
4. Browser begins downloading a `.zip` immediately (response headers flush before any track is transcoded).
5. Server resolves the URL, then for each video: downloads audio → transcodes to MP3 320 kbps → streams the MP3 bytes into a zip entry → the zip body flushes to the browser.
6. When done, browser shows the download as complete. If any tracks failed, a `_failed.txt` inside the zip lists them.

## 4. Architecture

### Stack
- **Backend:** Python 3.12 + FastAPI.
- **Engine:** `yt-dlp` (Python library, in-process — not subprocess).
- **Audio:** `ffmpeg` binary (called by yt-dlp's `FFmpegExtractAudio` postprocessor) for Opus → MP3 320 kbps transcode.
- **Streaming zip:** the `stream-zip` library (writes a real zip incrementally; no central-directory pre-pass needed).
- **Auth:** shared password from `APP_PASSWORD` env var; `itsdangerous` URLSafeTimedSerializer-signed session cookies (`SESSION_SECRET` env var); 30-day expiry.
- **Frontend:** one static HTML page served by FastAPI. Vanilla JS, no build step. Tailwind via CDN.
- **Deploy:** single Docker image (Python + ffmpeg). Railway-friendly. Same image runs locally.

### Process shape
One FastAPI process. No DB, no Redis, no background workers. A global `asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)` (default 2) caps concurrent download work to prevent thrashing the host.

### Request shape

```
[ Browser ] ──login form──▶ POST /login (password)  ──▶ Set-Cookie: session
[ Browser ] ──paste URL───▶ POST /download (cookie)  ──▶ application/zip stream
                                                         │
                                                         ▼
                                          yt-dlp (resolve + download)
                                                         │
                                                         ▼
                                           ffmpeg (transcode to MP3)
                                                         │
                                                         ▼
                                          stream-zip → response body
```

## 5. Components

Five small modules, each with a single purpose. Sized so each can be built and tested independently — suitable for parallel subagent execution at implementation time.

```
app/
  main.py          # FastAPI app, routes, startup
  auth.py          # password check + signed-cookie session
  resolver.py      # URL → list of video entries (single or playlist)
  pipeline.py      # video entry → MP3 bytes (yt-dlp + ffmpeg)
  zipstream.py     # async generator: entries → streaming zip body
  static/
    index.html     # login form + URL form
    app.js         # form submit, password gate, status text
```

### `auth.py`
- `verify_password(plain: str) -> bool` — constant-time compare against `APP_PASSWORD`.
- `make_session_cookie() -> str` and `verify_session_cookie(value: str) -> bool` — `itsdangerous` URLSafeTimedSerializer with `SESSION_SECRET`, 30-day max age.
- FastAPI dependency `require_session` that raises 401 if cookie is missing/invalid/expired.

### `resolver.py`
- `resolve(url: str) -> list[VideoEntry]` where `VideoEntry` is a dataclass with `id`, `webpage_url`, `title`, `uploader`.
- Implementation: `yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True}).extract_info(url, download=False)`.
- Single video → 1-element list; playlist → N entries.
- Validates hostname is in the allowlist (`youtube.com`, `www.youtube.com`, `m.youtube.com`, `music.youtube.com`, `youtu.be`) before invoking yt-dlp (defense-in-depth against SSRF). The same allowlist is referenced from §8.
- Raises `ResolveError` with a sanitized reason for: invalid URLs, non-YouTube hostnames, private videos, age-gated content, region-blocked content, live streams, upcoming premieres, playlists exceeding `MAX_PLAYLIST_SIZE` (default 100).

### `pipeline.py`
- `download_as_mp3(entry: VideoEntry) -> AsyncIterator[bytes]` — async generator yielding MP3 bytes in chunks (e.g. 64 KB).
- yt-dlp config: `format="bestaudio"`, `postprocessors=[FFmpegExtractAudio(codec="mp3", quality="320")]`, output to a `tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)`.
- Yields chunks from the temp file, then deletes it. Deletes the temp file on exception too (try/finally).
- Heavy synchronous work runs via `asyncio.to_thread` so the event loop isn't blocked.

### `zipstream.py`
- `stream_zip(entries: list[VideoEntry]) -> AsyncIterator[bytes]` — async generator yielding zip body bytes.
- Uses the `stream-zip` library to construct a valid zip incrementally.
- For each entry: sanitizes the title to a filesystem-safe filename, calls `pipeline.download_as_mp3`, feeds bytes into the zip stream, yields zip bytes outward.
- Per-entry try/except: a failed track is logged at WARNING and a `(title, reason)` tuple is appended to an in-memory failed list. Zip continues with remaining entries.
- After the last entry, if the failed list is non-empty, appends a `_failed.txt` zip entry listing skipped titles + reasons.

### `main.py`
- `GET /` — serves `index.html` if session cookie valid, else redirects to `/login`.
- `GET /login` — login form.
- `POST /login` — verifies password, sets signed session cookie (`HttpOnly`, `Secure`, `SameSite=Strict`), redirects to `/`.
- `POST /logout` — clears the cookie.
- `POST /download/preflight` — depends on `require_session`; JSON body `{url}`. Calls `resolver.resolve`, caches the result keyed by `(session_id, url)` with 60 s TTL, returns 200 `{entry_count, suggested_filename}` or 4xx error.
- `POST /download` — depends on `require_session`; body `{url}` (accepts JSON or form-encoded). Reuses the cached resolve result if present, else calls `resolver.resolve` fresh. Returns `StreamingResponse(zipstream.stream_zip(entries), media_type="application/zip")` with a sanitized `Content-Disposition: attachment; filename*=UTF-8''<safe>.zip`.
- Startup probe: runs `ffmpeg -version` once at app startup; refuses to start if missing.

### Frontend
Two states:
- **Logged-out:** password input + submit. POST to `/login`.
- **Logged-in:** URL input + submit.

**Submit flow** (resolves the error-rendering question — a hidden form alone can't render inline errors because an error response would replace the page):
1. JS submits the URL to `POST /download/preflight` (JSON, returns 200 `{entry_count, suggested_filename}` or 4xx with reason). Preflight runs `resolver.resolve` only — no transcoding, cheap.
2. On 4xx, render error inline. On 200, render "Preparing your download…" and submit a hidden form to `POST /download` so the browser handles the streaming response natively.
3. Server caches the resolve result by `(session_id, url)` for ~60 s so the second request doesn't repeat the network round-trip. In-memory dict, evicted on TTL.

Tailwind via CDN; no build step.

## 6. Data flow (one playlist download)

1. **Auth check:** `require_session` validates the cookie. 401 if invalid.
2. **Resolve:** `resolver.resolve(url)` returns the list of entries (1 for a single video). 1–3 s for a single video; 3–10 s for a playlist of ~50.
3. **Headers flush:** `StreamingResponse` returns; FastAPI sends `200 OK`, `Content-Type: application/zip`, `Content-Disposition: attachment; filename=…`. Browser opens its native download dialog.
4. **Per-track loop:** for each entry,
   - `pipeline.download_as_mp3` writes a temp `.mp3`, yields it in chunks, deletes the temp file.
   - `zipstream.stream_zip` wraps those chunks into a zip entry, yields zip bytes.
   - FastAPI flushes those bytes to the TCP socket → browser.
5. **Disk discipline:** at any moment, at most one temp `.mp3` exists per concurrent download.
6. **Per-track failure:** caught inside `zipstream`'s try/except; current zip entry closed cleanly; loop continues. Title + reason appended to the failed list.
7. **Completion:** after the last entry, `_failed.txt` is written if any failures occurred. The zip's central directory is emitted. Response ends.
8. **Connection drop mid-stream:** generator receives `CancelledError`; `pipeline`'s try/finally deletes its temp file. The browser's `.zip` is truncated and unreadable; user retries.

### Concurrency
- One download = one async request handler running blocking yt-dlp/ffmpeg work via `asyncio.to_thread`.
- A global `asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)` (default 2, env-tunable) caps concurrent downloads.
- A request that waits more than 30 s on the semaphore returns 503.

### Idempotency / caching
None. The same URL submitted twice yields two zips. Personal-scale doesn't benefit from caching here.

## 7. Error handling

| Where | Failure | User sees | Server does |
|---|---|---|---|
| Auth | wrong password | "Incorrect password" on login form | 401, no cookie set |
| Auth | expired/missing cookie on /download | redirect to /login | 401 from `require_session` |
| Resolve | invalid URL / non-YouTube host | inline error text | 400 with reason |
| Resolve | private / age-gated / region-blocked | inline error text | 400 with sanitized yt-dlp reason |
| Resolve | playlist > MAX_PLAYLIST_SIZE | inline error text | 413 "Playlist too large" |
| Resolve | YouTube anti-bot challenge ("Sign in to confirm…") | inline error + hint | 502 with hint to set `YT_COOKIES_FILE` |
| Resolve | live stream / upcoming premiere | inline error text | 400 |
| Pipeline | one track fails mid-zip | track listed in `_failed.txt` inside zip | log WARNING, continue |
| Pipeline | all tracks fail | zip with only `_failed.txt` (kept for visibility) | log ERROR |
| Pipeline | ffmpeg missing on host | inline error on first download | startup probe refuses to start without ffmpeg |
| Stream | client disconnect | nothing (browser canceled) | catch CancelledError, clean up temp file |
| Concurrency | semaphore full > 30 s | inline error "server busy, retry shortly" | 503 |
| Disk | tmp partition full | inline error | 507 + log; periodic cleanup task wipes orphan temp files |

### Critical decisions
- **Pre-stream errors** are normal HTTP responses (status + JSON body); the form renders them inline.
- **Mid-stream errors** can't change the HTTP status — headers are already on the wire. Per-track failures fold into `_failed.txt`. Catastrophic failures truncate the zip; user retries.
- **YouTube anti-bot** is the most likely real-world failure mode. The app supports an optional `YT_COOKIES_FILE` env var pointing to a Netscape-format cookies export from a logged-in browser. We pin a recent yt-dlp version and `pip install --upgrade yt-dlp` at container build time so updates ship by rebuilding.

### Logging
- Standard Python `logging`, INFO level, structured fields: `event`, `url`, `entry_count`, `failed_count`, `duration_ms`.
- One log line per request start, one per request end (or error).
- Per-track success at DEBUG; per-track failure at WARNING.
- Never log cookies, the session secret, the app password, or full URLs containing potentially sensitive query strings.

## 8. Security

- Constant-time password compare via `hmac.compare_digest`.
- Signed session cookies: `HttpOnly`, `Secure`, `SameSite=Strict`, 30-day expiry.
- **CSRF:** not separately mitigated. The session cookie's `SameSite=Strict` prevents cross-site form posts from carrying it; `/download` accepts both JSON and form bodies but always requires the session cookie.
- **SSRF:** resolver rejects any URL whose hostname is not in the allowlist (`youtube.com`, `www.youtube.com`, `youtu.be`, `m.youtube.com`, `music.youtube.com`) before passing to yt-dlp.
- **Filename injection in `Content-Disposition`:** RFC 5987 `filename*=UTF-8''…` with strict ASCII fallback; control chars (`\r`, `\n`) hard-stripped.
- **Filename sanitization for zip entries:** strip control chars, replace filesystem-unsafe chars (`/\:*?"<>|`) with `_`, fall back to `track_<n>.mp3` if the result is empty. Non-ASCII letters and digits are preserved.
- No rate limiting at the app layer for v1 — the shared password is the gate. If the app is ever exposed publicly, add IP-based rate limiting (e.g. `slowapi`) on `/login` and `/download`.

## 9. Configuration (env vars)

| Var | Required | Default | Purpose |
|---|---|---|---|
| `APP_PASSWORD` | yes | — | Shared login password |
| `SESSION_SECRET` | yes | — | Key for signing session cookies (≥ 32 random bytes) |
| `MAX_PLAYLIST_SIZE` | no | 100 | Reject playlists with more entries |
| `MAX_CONCURRENT_DOWNLOADS` | no | 2 | Global semaphore cap |
| `SEMAPHORE_WAIT_SECONDS` | no | 30 | How long a request waits for the semaphore before 503 |
| `YT_COOKIES_FILE` | no | unset | Path to Netscape-format YouTube cookies file (helps with anti-bot) |
| `LOG_LEVEL` | no | INFO | Python logging level |

App refuses to start if `APP_PASSWORD` or `SESSION_SECRET` are unset.

## 10. Testing

Tests target the bug-prone surface (streaming, zipping, error paths) and skip third-party-library behavior we don't own.

| Module | Test type | Coverage |
|---|---|---|
| `auth.py` | unit | password compare; cookie sign/verify roundtrip; expired cookie rejected; tampered cookie rejected |
| `resolver.py` | unit (mocked `yt_dlp.YoutubeDL`) | single video → 1 entry; playlist → N entries; non-YT URL → ResolveError; live stream → ResolveError; oversized playlist → ResolveError |
| `zipstream.py` | unit (real `stream-zip`, fake pipeline) | yields a valid zip; multi-entry zip; one-entry-fails → `_failed.txt` present; all-fail → zip contains only `_failed.txt`; filename sanitization |
| `pipeline.py` | unit (mocked `yt_dlp.YoutubeDL`) | yields chunked bytes; temp file deleted on success; temp file deleted on exception |
| `main.py` | integration via `httpx.AsyncClient` + `ASGITransport` | full /login → /download/preflight → /download flow with fake resolver+pipeline; preflight returns entry_count and caches; cached resolve reused on subsequent /download; cache evicted after TTL; 401 without cookie; 400 on bad URL; 413 on big playlist; 503 on semaphore exhaustion; client disconnect cleans up temp |
| smoke (opt-in, env-gated) | real network | one Creative Commons YouTube URL end-to-end; `pytest -m smoke`; not run in CI by default |

### Test infrastructure
- `pytest` + `pytest-asyncio`.
- `httpx.AsyncClient(transport=ASGITransport(app=app))` for in-process integration tests — no port binding.
- `FakePipeline` and `FakeResolver` fixtures so non-pipeline tests don't need yt-dlp or ffmpeg.

### What we deliberately don't test
- yt-dlp's behavior — third-party dep, not ours.
- ffmpeg's transcoding output quality — same reason.
- Filesystem-full / OOM scenarios — too expensive for the value.
- Browser-side JS — small enough to verify by hand.

### TDD discipline
The implementation plan will follow test-driven development: each module's tests are written and failing first, then implementation makes them pass.

## 11. Deployment

- **Dockerfile:** `python:3.12-slim` base, install ffmpeg via apt, `pip install` requirements (pinned), copy app code, run `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- **Railway:** connect GitHub repo, set required env vars, deploy on push to `main`. Volume not required (no persistent state). Cookies file (if used) is mounted as a Railway secret file.
- **Local:** `docker run -e APP_PASSWORD=… -e SESSION_SECRET=… -p 8000:8000 udown` — same image, same env vars.
- **Disclosure:** YouTube actively blocks cloud provider IP ranges. Railway deployments may start failing within hours of going live. The `YT_COOKIES_FILE` workaround helps but isn't permanent. Self-hosting on a residential IP is the most reliable option for sustained use.

## 12. Implementation parallelism

The five modules are designed for independent build and test. The implementation plan will explicitly carve work into parallel tasks:

- **Track A:** `auth.py` + its tests (no dependencies).
- **Track B:** `resolver.py` + its tests (no dependencies).
- **Track C:** `pipeline.py` + its tests (no dependencies).
- **Track D:** `zipstream.py` + its tests (depends on a `Pipeline` interface — fake in tests).
- **Track E:** Dockerfile + CI.
- **Integration:** `main.py` + integration tests (depends on A–D).
- **Frontend:** `index.html` + `app.js` (depends only on the HTTP contract, can run in parallel with backend).

A–E and Frontend can be dispatched as parallel subagents. Integration runs after the rest land.

## 13. Open questions

None at spec time. Any open implementation-level questions will be raised when writing the plan.
