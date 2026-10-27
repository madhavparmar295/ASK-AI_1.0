import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Notification, User
from ..security.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    ticket_id: Optional[uuid.UUID]
    text: str
    read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(id=n.id, ticket_id=n.ticket_id, text=n.text, read=n.read, created_at=n.created_at)


@router.get("", response_model=NotificationPage)
def list_notifications(unread_only: bool = False, limit: int = Query(20, ge=1, le=100),
                       offset: int = Query(0, ge=0), user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read.is_(False))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    unread = db.scalar(select(func.count()).select_from(Notification)
                       .where(Notification.user_id == user.id, Notification.read.is_(False))) or 0
    rows = db.scalars(q.order_by(Notification.created_at.desc()).limit(limit).offset(offset)).all()
    return NotificationPage(items=[_out(n) for n in rows], total=total, unread=unread)


@router.get("/unread-count")
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.scalar(select(func.count()).select_from(Notification)
                  .where(Notification.user_id == user.id, Notification.read.is_(False))) or 0
    return {"unread": n}


@router.post("/read-all")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))
               .values(read=True))
    db.commit()
    return {"ok": True}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    n.read = True
    db.commit()
    return _out(n)
