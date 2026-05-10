import os
from dataclasses import dataclass
from urllib.parse import urlparse

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


class ResolveError(Exception):
    """User-facing resolution failure."""


@dataclass(frozen=True)
class VideoEntry:
    id: str
    webpage_url: str
    title: str
    uploader: str = ""


def _extract(url: str) -> dict:
    """Wrap yt-dlp extract_info. Mocked in tests."""
    import yt_dlp  # imported lazily so tests don't need it loaded at import time

    opts = {"extract_flat": True, "quiet": True, "no_warnings": True}
    cookies = os.environ.get("YT_COOKIES_FILE")
    if cookies:
        opts["cookiefile"] = cookies
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _validate_hostname(url: str) -> None:
    try:
        parsed = urlparse(url)
    except ValueError as e:
        raise ResolveError(f"invalid URL: {e}") from e
    if not parsed.scheme or not parsed.netloc:
        raise ResolveError("invalid URL: missing scheme or host")
    host = parsed.netloc.lower().split(":")[0]
    if host not in ALLOWED_HOSTS:
        raise ResolveError(f"hostname not allowed: {host}")


def _entry_from_info(info: dict) -> VideoEntry:
    if info.get("is_live"):
        raise ResolveError("live streams are not supported")
    if info.get("live_status") == "is_upcoming":
        raise ResolveError("upcoming/live premieres are not supported")
    return VideoEntry(
        id=info.get("id", ""),
        webpage_url=info.get("webpage_url") or info.get("url", ""),
        title=info.get("title", "") or "untitled",
        uploader=info.get("uploader", "") or "",
    )


def resolve(url: str) -> list[VideoEntry]:
    _validate_hostname(url)
    try:
        info = _extract(url)
    except ResolveError:
        raise
    except Exception as e:
        raise ResolveError(f"could not resolve URL: {e}") from e

    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        max_size = int(os.environ.get("MAX_PLAYLIST_SIZE", "100"))
        if len(entries) > max_size:
            raise ResolveError(
                f"playlist too large: {len(entries)} entries (max {max_size})"
            )
        return [_entry_from_info(e) for e in entries if e]
    return [_entry_from_info(info)]
