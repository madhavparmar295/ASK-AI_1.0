"""CSRF protection for every state-changing request.

The front end must send the value of the `grievance_csrf` cookie in an
`X-CSRF-Token` header. We compare it with the token stored inside the signed
session cookie. Requests without a session are skipped here; the auth
dependency rejects them anyway.
"""
import hmac

from fastapi import HTTPException, Request

from .sessions import SESSION_COOKIE, read_session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_SUFFIXES = ("/auth/google", "/auth/dev-login")  # no session exists yet


async def csrf_protect(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    if request.url.path.endswith(EXEMPT_SUFFIXES):
        return
    data = read_session(request.cookies.get(SESSION_COOKIE))
    if not data:
        return
    header = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(header, data["csrf"]):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
