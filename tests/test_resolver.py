from unittest.mock import patch

import pytest

from app.resolver import VideoEntry, ResolveError, resolve

# yt-dlp returns a dict like {"_type": "video", ...} for a single video,
# or {"_type": "playlist", "entries": [...]} for a playlist (with extract_flat).


def _video_info(vid="abc", title="A", uploader="U"):
    return {
        "_type": "video",
        "id": vid,
        "url": f"https://youtube.com/watch?v={vid}",
        "webpage_url": f"https://youtube.com/watch?v={vid}",
        "title": title,
        "uploader": uploader,
        "is_live": False,
        "live_status": None,
    }


def _playlist_info(entries):
    return {
        "_type": "playlist",
        "title": "My Playlist",
        "entries": entries,
    }


@patch("app.resolver._extract")
def test_resolve_single_video(extract):
    extract.return_value = _video_info()
    out = resolve("https://youtube.com/watch?v=abc")
    assert len(out) == 1
    assert out[0].id == "abc"
    assert out[0].title == "A"
    assert out[0].webpage_url == "https://youtube.com/watch?v=abc"


@patch("app.resolver._extract")
def test_resolve_playlist(extract):
    extract.return_value = _playlist_info(
        [_video_info("a"), _video_info("b"), _video_info("c")]
    )
    out = resolve("https://youtube.com/playlist?list=PL123")
    assert [e.id for e in out] == ["a", "b", "c"]


def test_resolve_rejects_non_youtube_host():
    with pytest.raises(ResolveError, match="hostname"):
        resolve("https://example.com/watch?v=abc")


def test_resolve_rejects_garbage_url():
    with pytest.raises(ResolveError):
        resolve("not-a-url")


@patch("app.resolver._extract")
def test_resolve_rejects_live_stream(extract):
    info = _video_info()
    info["is_live"] = True
    extract.return_value = info
    with pytest.raises(ResolveError, match="live"):
        resolve("https://youtube.com/watch?v=abc")


@patch("app.resolver._extract")
def test_resolve_rejects_upcoming_premiere(extract):
    info = _video_info()
    info["live_status"] = "is_upcoming"
    extract.return_value = info
    with pytest.raises(ResolveError, match="upcoming|live"):
        resolve("https://youtube.com/watch?v=abc")


@patch("app.resolver._extract")
def test_resolve_rejects_oversized_playlist(extract, monkeypatch):
    monkeypatch.setenv("MAX_PLAYLIST_SIZE", "2")
    extract.return_value = _playlist_info(
        [_video_info(str(i)) for i in range(5)]
    )
    with pytest.raises(ResolveError, match="too large|playlist"):
        resolve("https://youtube.com/playlist?list=PL123")


@patch("app.resolver._extract")
def test_resolve_accepts_youtu_be(extract):
    extract.return_value = _video_info()
    out = resolve("https://youtu.be/abc")
    assert len(out) == 1


@patch("app.resolver._extract")
def test_resolve_accepts_music_youtube(extract):
    extract.return_value = _video_info()
    out = resolve("https://music.youtube.com/watch?v=abc")
    assert len(out) == 1
