"""Authentication and role dependencies used by every route."""
import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from .sessions import SESSION_COOKIE, read_session


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    data = read_session(request.cookies.get(SESSION_COOKIE))
    if not data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user = db.get(User, uuid.UUID(data["uid"]))
    except (ValueError, KeyError):
        user = None
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_role(*roles: str):
    """Dependency factory. Wrong role returns 404 so protected pages are not revealed."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=404, detail="Not found")
        return user
    return checker
