# uDown

A small password-gated FastAPI web app that turns a YouTube URL into a streaming MP3 zip download. Personal-scale; not designed for public exposure.

## Features

- Single videos and playlists (capped at 100 by default)
- 320 kbps MP3 output, browser-streamed `.zip`
- Shared password auth with 30-day signed session cookie
- One Docker image, no DB, no background workers

## Quickstart (local)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

export APP_PASSWORD=hunter2
export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000.

## Docker

```bash
docker build -t udown .
docker run -p 8000:8000 \
  -e APP_PASSWORD=hunter2 \
  -e SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  -e UDOWN_COOKIE_SECURE=1 \
  udown
```

## Running on someone else's Linux box

Pre-built images are published to GitHub Container Registry on every push to
`main` (see `.github/workflows/docker.yml`). The image must be made **public**
once via the GitHub UI (Settings → Packages → udown → Change visibility) before
unauthenticated pulls work.

After that, anyone on Linux/macOS with Docker installed can run:

```bash
curl -fsSL https://raw.githubusercontent.com/Kathail/uDown/main/scripts/run.sh -o udown.sh
chmod +x udown.sh
./udown.sh
```

The launcher generates an `APP_PASSWORD` + `SESSION_SECRET` on first run (stored
in `~/.local/share/udown/env`, mode 0600), pulls the latest image, and starts
the container on `http://localhost:8000`. The password is printed to the
terminal. After logging in, paste your YouTube cookies into the cookies panel
and start downloading.

### One-click on Linux (desktop launcher)

Download `udown.desktop`, mark it executable, double-click. The first time on
GNOME/KDE the file manager asks you to confirm — right-click → **Allow
Launching** (GNOME) or **Properties → Permissions → Is executable** (KDE).

```bash
curl -fsSL https://raw.githubusercontent.com/Kathail/uDown/main/scripts/udown.desktop -o ~/Desktop/udown.desktop
chmod +x ~/Desktop/udown.desktop
```

To make it show up in the app menu instead of just on the desktop:

```bash
mkdir -p ~/.local/share/applications
cp ~/Desktop/udown.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
```

Prereq: Docker installed and the user in the `docker` group. On Nobara/Fedora:

```bash
sudo dnf install -y moby-engine
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
# log out and back in
```

## Deploying to Railway

1. Push this repo to GitHub.
2. Create a new Railway service from the GitHub repo (Railway auto-detects the Dockerfile).
3. Set env vars in the Railway dashboard:
   - `APP_PASSWORD` (required)
   - `SESSION_SECRET` (required, ≥ 32 chars; generate with `openssl rand -base64 32`)
   - `UDOWN_COOKIE_SECURE=1` (recommended for HTTPS deploys)
   - `MAX_CONCURRENT_DOWNLOADS=2` (optional)
   - `MAX_PLAYLIST_SIZE=100` (optional)
   - `YT_COOKIES_FILE=/data/cookies.txt` (optional — see below)
4. Deploy.

### Heads-up on cloud hosting

YouTube actively blocks IP ranges from cloud providers (Railway, Render, Fly, etc.). Downloads from cloud IPs may start failing within hours of going live with a "Sign in to confirm you're not a bot" error.

Workarounds:
- **`YT_COOKIES_FILE`**: export cookies from a logged-in browser using the cookies.txt extension, mount it as a Railway volume or secret file, point this env var at the path.
- **Self-host on a residential IP**: the most reliable option for sustained use.

## Environment variables

| Var | Required | Default | Purpose |
|---|---|---|---|
| `APP_PASSWORD` | yes | — | Shared login password |
| `SESSION_SECRET` | yes | — | Key for signing session cookies (≥ 32 random bytes) |
| `MAX_PLAYLIST_SIZE` | no | 100 | Reject playlists with more entries |
| `MAX_CONCURRENT_DOWNLOADS` | no | 2 | Global semaphore cap |
| `SEMAPHORE_WAIT_SECONDS` | no | 30 | How long a request waits for the semaphore before 503 |
| `YT_COOKIES_FILE` | no | unset | Path to Netscape-format YouTube cookies file (helps with anti-bot) |
| `UDOWN_COOKIE_SECURE` | no | 0 | Set to `1` to mark session cookie Secure (HTTPS only) |
| `LOG_LEVEL` | no | INFO | Python logging level |

## Tests

```bash
.venv/bin/pytest -v             # unit + integration
.venv/bin/pytest -m smoke -v    # opt-in, hits real YouTube
```

## Architecture & design

See `docs/superpowers/specs/2026-05-09-udown-design.md` and `docs/superpowers/plans/2026-05-09-udown.md`.
