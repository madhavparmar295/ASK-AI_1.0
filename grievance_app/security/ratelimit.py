"""Small in-memory rate limiter (per process).

Good enough for one server process. If you run several workers, each has its
own counter, so the real limit is higher; note this in the runbook.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from ..config import get_settings

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def reset() -> None:
    with _lock:
        _hits.clear()


def check(key: str, limit: int, window_seconds: int = 60) -> None:
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
        q.append(now)


def login_rate_limit(request: Request) -> None:
    # Behind the reverse proxy, configure it to pass the real client IP
    # (and run uvicorn with --proxy-headers) so this is not the proxy's address.
    ip = request.client.host if request.client else "unknown"
    check(f"login:{ip}", get_settings().login_rate_limit_per_minute)
