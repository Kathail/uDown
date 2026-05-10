import hmac
import os

from fastapi import Cookie, HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "udown_session"
SESSION_MAX_AGE = 30 * 86400  # 30 days


def _password() -> str:
    pw = os.environ.get("APP_PASSWORD")
    if not pw:
        raise RuntimeError("APP_PASSWORD env var is required")
    return pw


def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("SESSION_SECRET")
    if not secret or len(secret) < 32:
        raise RuntimeError("SESSION_SECRET env var must be at least 32 chars")
    return URLSafeTimedSerializer(secret, salt="udown-session")


def verify_password(plain: str) -> bool:
    expected = _password()
    return hmac.compare_digest(plain.encode("utf-8"), expected.encode("utf-8"))


def make_session_cookie() -> str:
    return _serializer().dumps("ok")


def verify_session_cookie(value: str) -> bool:
    if not value:
        return False
    try:
        _serializer().loads(value, max_age=SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_session(udown_session: str | None = Cookie(default=None)) -> None:
    if not verify_session_cookie(udown_session or ""):
        raise HTTPException(status_code=401, detail="not authenticated")
