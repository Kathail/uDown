import time

import pytest
from itsdangerous import BadSignature

from app.auth import (
    verify_password,
    make_session_cookie,
    verify_session_cookie,
)


def test_verify_password_correct():
    assert verify_password("test-password") is True


def test_verify_password_incorrect():
    assert verify_password("wrong") is False


def test_verify_password_empty():
    assert verify_password("") is False


def test_session_cookie_roundtrip():
    cookie = make_session_cookie()
    assert verify_session_cookie(cookie) is True


def test_session_cookie_tampered():
    cookie = make_session_cookie()
    tampered = cookie[:-1] + ("x" if cookie[-1] != "x" else "y")
    assert verify_session_cookie(tampered) is False


def test_session_cookie_garbage():
    assert verify_session_cookie("not-a-real-cookie") is False


def test_session_cookie_empty():
    assert verify_session_cookie("") is False


def test_session_cookie_expired(monkeypatch):
    """A cookie older than 30 days is rejected."""
    cookie = make_session_cookie()
    # Travel forward 31 days. itsdangerous uses time.time() internally.
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 31 * 86400)
    assert verify_session_cookie(cookie) is False
