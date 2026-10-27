from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import Role
from ..db import get_db
from ..models import Routing, User
from ..schemas import DevLoginIn, DevUserOut, GoogleLoginIn, MeOut
from ..security.deps import get_current_user
from ..security.ratelimit import login_rate_limit
from ..security.sessions import (clear_session_cookies, create_session,
                                 set_session_cookies)
from . import google
from .google import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["me"])


def _is_head(db: Session, user: User) -> bool:
    return bool(db.scalar(select(exists().where(or_(
        Routing.level1_user_id == user.id, Routing.level2_user_id == user.id)))))


def _me(db: Session, user: User, csrf: str | None = None) -> MeOut:
    out = MeOut.model_validate(user)
    out.is_head = _is_head(db, user)
    out.csrf_token = csrf
    return out


def _start_session(db: Session, user: User, response: Response) -> MeOut:
    token, csrf = create_session(user.id)
    set_session_cookies(response, token, csrf)
    return _me(db, user, csrf)


@router.post("/google", response_model=MeOut, dependencies=[Depends(login_rate_limit)])
def google_login(body: GoogleLoginIn, response: Response, db: Session = Depends(get_db)):
    try:
        info = google.verify_google_credential(body.credential)
    except AuthError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    user = db.scalar(select(User).where(User.email == info["email"]))
    if user is None:
        if get_settings().unknown_email_policy != "student":
            raise HTTPException(status_code=403, detail="This account is not registered. Contact the admin office.")
        user = User(name=info["name"], email=info["email"], role=Role.STUDENT)
        db.add(user)
        db.commit()
    if not user.active:
        raise HTTPException(status_code=403, detail="This account is deactivated")
    return _start_session(db, user, response)


def _require_dev_login() -> None:
    s = get_settings()
    if not s.dev_login_enabled or s.is_production:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/dev-users", response_model=list[DevUserOut], dependencies=[Depends(_require_dev_login)])
def dev_users(db: Session = Depends(get_db)):
    """Feeds the fake-user picker. Development only."""
    users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.role, User.name)).all()
    return [DevUserOut(email=u.email, name=u.name, role=u.role) for u in users]


@router.post("/dev-login", response_model=MeOut,
             dependencies=[Depends(_require_dev_login), Depends(login_rate_limit)])
def dev_login(body: DevLoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.active:
        raise HTTPException(status_code=404, detail="User not found")
    return _start_session(db, user, response)


@router.post("/logout")
def logout(response: Response):
    clear_session_cookies(response)
    return {"ok": True}


@me_router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _me(db, user)
