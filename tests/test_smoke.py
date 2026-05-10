"""
Real-network smoke test. Run with: pytest -m smoke

Requires ffmpeg on PATH and outbound internet access.
"""
import io
import zipfile

import httpx
import pytest
from httpx import ASGITransport


# "Me at the zoo" — the first YouTube video, 19s, public. Pick a different
# stable URL if this ever rots.
SMOKE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@pytest.mark.smoke
async def test_smoke_real_download():
    from app.main import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as c:
        await c.post("/login", data={"password": "test-password"})
        r = await c.post("/download", data={"url": SMOKE_URL})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/zip")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        assert len(names) >= 1
        # First entry should be a non-empty MP3.
        first = [n for n in names if n.endswith(".mp3")][0]
        data = zf.read(first)
        assert len(data) > 10_000  # non-trivial
        # MP3 frames start with 0xFFFB or 0xFFF3 etc., or ID3 header.
        assert data[:3] == b"ID3" or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)
