import logging
import re
from datetime import datetime
from stat import S_IFREG
from typing import AsyncIterator, Callable

from stream_zip import ZIP_64, async_stream_zip

from app.resolver import VideoEntry

log = logging.getLogger(__name__)

PipelineFn = Callable[[VideoEntry], AsyncIterator[bytes]]

_BAD_FS_CHARS = re.compile(r'[\\/:*?"<>|]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(title: str, index: int = 0) -> str:
    """Filesystem-safe stem (no extension). Falls back to 'track_<index>'."""
    cleaned = _CONTROL_CHARS.sub("", title or "")
    cleaned = _BAD_FS_CHARS.sub("_", cleaned)
    cleaned = cleaned.strip().strip(".").strip("_")
    if not cleaned:
        return f"track_{index}"
    return cleaned[:200]  # cap length to avoid pathological filenames


def _dedupe(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    n = 2
    while f"{name} ({n})" in used:
        n += 1
    final = f"{name} ({n})"
    used.add(final)
    return final


async def _peeked_pipeline(
    entry: VideoEntry,
    pipeline: PipelineFn,
    failed: list[tuple[str, str]],
) -> tuple[bool, AsyncIterator[bytes] | None, bytes | None]:
    """
    Try to get the first chunk from the pipeline.

    Returns (success, async_iter_of_remaining, first_chunk).
    If the pipeline raises before yielding, records the failure and returns
    (False, None, None).
    """
    it = pipeline(entry).__aiter__()
    try:
        first_chunk = await it.__anext__()
    except StopAsyncIteration:
        # Pipeline yielded nothing (but didn't raise) — treat as empty success.
        return True, _empty_iter(), b""
    except Exception as e:
        failed.append((entry.title, str(e)))
        log.warning("zipstream: skipping %s: %s", entry.title, e)
        return False, None, None
    return True, it, first_chunk


async def _empty_iter() -> AsyncIterator[bytes]:
    return
    yield  # make it an async generator


async def _chain(first_chunk: bytes, rest: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Yield first_chunk then all chunks from rest."""
    yield first_chunk
    async for chunk in rest:
        yield chunk


async def stream_zip(
    entries: list[VideoEntry],
    pipeline: PipelineFn,
) -> AsyncIterator[bytes]:
    """Stream a zip body containing one MP3 per successful entry.

    `pipeline` is a callable returning an async iterator of bytes for an entry.
    Failures during a single entry are caught: the entry is skipped and listed
    in `_failed.txt` appended at the end.
    """
    failed: list[tuple[str, str]] = []
    used_names: set[str] = set()
    now = datetime.now()
    perms = 0o600

    async def members():
        for idx, entry in enumerate(entries):
            success, rest_iter, first_chunk = await _peeked_pipeline(
                entry, pipeline, failed
            )
            if not success:
                # Pipeline raised before producing any data — skip this entry.
                continue

            stem = sanitize_filename(entry.title, index=idx)
            stem = _dedupe(stem, used_names)
            filename = f"{stem}.mp3"

            if first_chunk == b"" and rest_iter is not None:
                # Edge case: pipeline yielded nothing (StopAsyncIteration immediately)
                data_iter = _empty_iter()
            else:
                data_iter = _chain(first_chunk, rest_iter)

            yield (
                filename,
                now,
                S_IFREG | perms,
                ZIP_64,
                data_iter,
            )

        if failed:
            body = "\n".join(f"{title}: {reason}" for title, reason in failed) + "\n"
            yield (
                "_failed.txt",
                now,
                S_IFREG | perms,
                ZIP_64,
                _bytes_iter(body.encode("utf-8")),
            )

    async for chunk in async_stream_zip(members()):
        yield chunk


async def _bytes_iter(data: bytes) -> AsyncIterator[bytes]:
    yield data
