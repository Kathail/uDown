import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.pipeline import download_as_mp3
from app.resolver import VideoEntry


@pytest.fixture
def entry():
    return VideoEntry(id="x", webpage_url="https://youtube.com/watch?v=x", title="T")


def _make_fake_download(content: bytes):
    """
    Returns a fake _ydl_download function that:
    1. Reads tmp_path from kwargs.
    2. Writes `content` to that path (simulating yt-dlp + ffmpeg producing an MP3).
    """

    def fake(entry, tmp_path):
        Path(tmp_path).write_bytes(content)

    return fake


@patch("app.pipeline._ydl_download")
async def test_download_yields_chunks(ydl_dl, entry):
    ydl_dl.side_effect = _make_fake_download(b"A" * 200_000)
    chunks = []
    async for c in download_as_mp3(entry):
        chunks.append(c)
    assert b"".join(chunks) == b"A" * 200_000
    assert len(chunks) >= 2  # confirm it actually chunked


@patch("app.pipeline._ydl_download")
async def test_download_deletes_temp_on_success(ydl_dl, entry, tmp_path, monkeypatch):
    seen_paths = []

    def fake(entry, p):
        seen_paths.append(p)
        Path(p).write_bytes(b"hi")

    ydl_dl.side_effect = fake
    async for _ in download_as_mp3(entry):
        pass
    # After completion, the temp file should not exist.
    assert seen_paths
    assert not Path(seen_paths[0]).exists()


@patch("app.pipeline._ydl_download")
async def test_download_deletes_temp_on_exception(ydl_dl, entry):
    seen = []

    def fake(entry, p):
        seen.append(p)
        Path(p).write_bytes(b"partial")
        raise RuntimeError("yt-dlp blew up")

    ydl_dl.side_effect = fake
    with pytest.raises(RuntimeError):
        async for _ in download_as_mp3(entry):
            pass
    assert seen
    assert not Path(seen[0]).exists()
