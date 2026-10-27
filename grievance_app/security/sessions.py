"""Signed session cookie. The cookie holds only the user id and a CSRF token."""
import secrets
from typing import Optional

from fastapi import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import get_settings

SESSION_COOKIE = "grievance_session"
CSRF_COOKIE = "grievance_csrf"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="grievance-session")


def create_session(user_id) -> tuple[str, str]:
    csrf = secrets.token_urlsafe(32)
    token = _serializer().dumps({"uid": str(user_id), "csrf": csrf})
    return token, csrf


def read_session(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=get_settings().session_ttl_hours * 3600)
    except (BadSignature, SignatureExpired):
        return None


def set_session_cookies(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    max_age = s.session_ttl_hours * 3600
    # Session cookie: not readable by JavaScript.
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True,
                        secure=s.cookie_secure, samesite="lax", path="/")
    # CSRF cookie: readable by the front end, which echoes it in X-CSRF-Token.
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False,
                        secure=s.cookie_secure, samesite="lax", path="/")


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
