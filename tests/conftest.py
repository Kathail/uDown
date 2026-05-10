import os
from dataclasses import dataclass

import pytest


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    """Provide required env vars for every test."""
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("MAX_PLAYLIST_SIZE", "100")
    monkeypatch.setenv("MAX_CONCURRENT_DOWNLOADS", "2")
    monkeypatch.setenv("SEMAPHORE_WAIT_SECONDS", "30")


@dataclass
class FakeEntry:
    id: str
    webpage_url: str
    title: str
    uploader: str = "Fake Uploader"


@pytest.fixture
def fake_entry():
    return FakeEntry(
        id="abc123",
        webpage_url="https://youtube.com/watch?v=abc123",
        title="Test Track",
    )


@pytest.fixture
def fake_entries():
    return [
        FakeEntry(id="a1", webpage_url="https://youtube.com/watch?v=a1", title="Track One"),
        FakeEntry(id="b2", webpage_url="https://youtube.com/watch?v=b2", title="Track Two"),
        FakeEntry(id="c3", webpage_url="https://youtube.com/watch?v=c3", title="Track Three"),
    ]
