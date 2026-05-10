import io
import zipfile

import pytest

from app.zipstream import sanitize_filename, stream_zip
from app.resolver import VideoEntry


def _entries(*titles):
    return [
        VideoEntry(id=str(i), webpage_url=f"https://youtube.com/watch?v={i}", title=t)
        for i, t in enumerate(titles)
    ]


async def _collect(agen):
    out = bytearray()
    async for chunk in agen:
        out.extend(chunk)
    return bytes(out)


# ---- filename sanitization -----------------------------------------------


def test_sanitize_strips_path_separators():
    assert sanitize_filename("a/b\\c") == "a_b_c"


def test_sanitize_strips_control_chars():
    assert sanitize_filename("hi\x00\x01world") == "hiworld"


def test_sanitize_replaces_filesystem_unsafe():
    assert sanitize_filename('a:b*c?d"e<f>g|h') == "a_b_c_d_e_f_g_h"


def test_sanitize_preserves_unicode_letters():
    assert sanitize_filename("Bjørk – Hyperballad") == "Bjørk – Hyperballad"


def test_sanitize_empty_falls_back_to_track_n():
    assert sanitize_filename("", index=3) == "track_3"
    assert sanitize_filename("///", index=7) == "track_7"


# ---- streaming zip --------------------------------------------------------


async def _fake_pipeline_ok(entry):
    yield f"audio-of-{entry.id}".encode()


async def _fake_pipeline_fail_id(fail_ids):
    async def pipeline(entry):
        if entry.id in fail_ids:
            raise RuntimeError(f"boom on {entry.id}")
        yield f"audio-of-{entry.id}".encode()

    return pipeline


async def test_stream_zip_yields_valid_zip():
    entries = _entries("Track A", "Track B")
    body = await _collect(stream_zip(entries, pipeline=_fake_pipeline_ok))
    zf = zipfile.ZipFile(io.BytesIO(body))
    names = sorted(zf.namelist())
    assert names == ["Track A.mp3", "Track B.mp3"]
    assert zf.read("Track A.mp3") == b"audio-of-0"
    assert zf.read("Track B.mp3") == b"audio-of-1"


async def test_stream_zip_one_entry_fails_appends_failed_txt():
    entries = _entries("Good", "Bad", "Also Good")
    pipeline = await _fake_pipeline_fail_id({"1"})
    body = await _collect(stream_zip(entries, pipeline=pipeline))
    zf = zipfile.ZipFile(io.BytesIO(body))
    names = set(zf.namelist())
    assert "Good.mp3" in names
    assert "Also Good.mp3" in names
    assert "Bad.mp3" not in names
    assert "_failed.txt" in names
    failed = zf.read("_failed.txt").decode()
    assert "Bad" in failed
    assert "boom on 1" in failed


async def test_stream_zip_all_fail_only_failed_txt():
    entries = _entries("X", "Y")
    pipeline = await _fake_pipeline_fail_id({"0", "1"})
    body = await _collect(stream_zip(entries, pipeline=pipeline))
    zf = zipfile.ZipFile(io.BytesIO(body))
    assert zf.namelist() == ["_failed.txt"]


async def test_stream_zip_dedupes_filenames():
    """Two tracks with the same sanitized title get distinct names."""
    entries = _entries("Same", "Same")
    body = await _collect(stream_zip(entries, pipeline=_fake_pipeline_ok))
    zf = zipfile.ZipFile(io.BytesIO(body))
    names = sorted(zf.namelist())
    assert names == ["Same (2).mp3", "Same.mp3"]


async def test_stream_zip_mid_stream_failure_closes_entry_and_continues():
    """A pipeline that yields chunks then raises mid-stream:
    - the partial file entry closes cleanly with the bytes already streamed
    - the failure is recorded in _failed.txt
    - subsequent entries proceed
    """
    entries = _entries("Good", "Flaky", "Also Good")

    async def pipeline(entry):
        if entry.id == "1":
            yield b"first-good-chunk-"
            yield b"second-chunk-"
            raise RuntimeError("network reset")
        yield f"audio-of-{entry.id}".encode()

    body = await _collect(stream_zip(entries, pipeline=pipeline))
    zf = zipfile.ZipFile(io.BytesIO(body))
    names = set(zf.namelist())

    assert "Good.mp3" in names
    assert "Also Good.mp3" in names
    assert "Flaky.mp3" in names  # partial entry preserved
    assert "_failed.txt" in names

    # Partial entry contains what was streamed before the exception.
    flaky = zf.read("Flaky.mp3")
    assert flaky == b"first-good-chunk-second-chunk-"

    # Successful entries are unaffected.
    assert zf.read("Good.mp3") == b"audio-of-0"
    assert zf.read("Also Good.mp3") == b"audio-of-2"

    # Failure is recorded.
    failed = zf.read("_failed.txt").decode()
    assert "Flaky" in failed
    assert "network reset" in failed
