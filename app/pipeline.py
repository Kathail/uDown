import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncIterator

from app.resolver import VideoEntry

CHUNK_SIZE = 64 * 1024


def _ydl_download(entry: VideoEntry, output_path: str) -> None:
    """
    Synchronous yt-dlp + ffmpeg call. Writes a 320kbps MP3 to `output_path`.
    Mocked in tests.
    """
    import yt_dlp

    # yt-dlp's FFmpegExtractAudio postprocessor replaces the file's extension
    # to match the target codec, so we strip the .mp3 from outtmpl.
    base = output_path[:-4] if output_path.endswith(".mp3") else output_path
    opts = {
        "format": "bestaudio/best",
        "outtmpl": base + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ],
    }
    cookies = os.environ.get("YT_COOKIES_FILE")
    if cookies:
        opts["cookiefile"] = cookies
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([entry.webpage_url])


async def download_as_mp3(entry: VideoEntry) -> AsyncIterator[bytes]:
    """Yield MP3 bytes for `entry`. Cleans up temp file in all exit paths."""
    fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        await asyncio.to_thread(_ydl_download, entry, tmp_path)
        with open(tmp_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
