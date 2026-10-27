"""Admin oversight API (task T15, API half): statistics, ticket list, system health."""
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import Role, Status
from ..db import get_db
from ..models import Category, Feedback, Notification, Ticket, User
from ..permissions import ticket_visibility_filter
from ..schemas_tickets import TicketPage
from ..security.deps import require_role
from ..services import serializers
from ..services.errors import ServiceError
from ..services.scheduler import HEARTBEAT, heartbeat_age_minutes
from ..services.state import get_state
from ..services.tickets import aware, overdue_clause, utcnow

admin_only = require_role(Role.ADMIN)
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_only)])


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    """Counts only. Confidential tickets are counted but never listed."""
    now = utcnow()
    by_status = {s: 0 for s in Status.ALL}
    for status, n in db.execute(select(Ticket.status, func.count()).group_by(Ticket.status)).all():
        by_status[status] = n
    overdue_by_cat = dict(db.execute(select(Ticket.category_id, func.count()).where(overdue_clause(now))
                                     .group_by(Ticket.category_id)).all())
    open_by_cat = dict(db.execute(select(Ticket.category_id, func.count()).where(Ticket.status.in_(Status.OPEN))
                                  .group_by(Ticket.category_id)).all())
    total_by_cat = dict(db.execute(select(Ticket.category_id, func.count()).group_by(Ticket.category_id)).all())
    week = now - timedelta(days=7)
    avg, count = db.execute(select(func.avg(Feedback.rating), func.count()).select_from(Feedback)).one()
    return {
        "tickets": {
            "total": sum(by_status.values()),
            "open": sum(by_status[s] for s in Status.OPEN),
            "overdue": sum(overdue_by_cat.values()),
            "by_status": by_status,
            "created_last_7_days": db.scalar(select(func.count()).select_from(Ticket).where(Ticket.created_at >= week)) or 0,
            "closed_last_7_days": db.scalar(select(func.count()).select_from(Ticket).where(Ticket.closed_at >= week)) or 0,
        },
        "by_category": [
            {"category_id": str(c.id), "category": c.name, "confidential": c.confidential,
             "total": total_by_cat.get(c.id, 0), "open": open_by_cat.get(c.id, 0), "overdue": overdue_by_cat.get(c.id, 0)}
            for c in db.scalars(select(Category).order_by(Category.name)).all()],
        "feedback": {"count": count, "average": round(float(avg), 2) if avg is not None else None},
        "emails_waiting": db.scalar(select(func.count()).select_from(Notification).where(
            Notification.email_sent.is_(False), Notification.email_attempts < get_settings().email_max_attempts)) or 0,
    }


@router.get("/issues", response_model=TicketPage)
def all_issues(status: Optional[str] = None, category_id: Optional[uuid.UUID] = None, overdue: bool = False,
               q: Optional[str] = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
               admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    """All tickets the admin may see: confidential ones are excluded by the same visibility rule as everywhere."""
    if status is not None and status not in Status.ALL:
        raise ServiceError(422, "Unknown status")
    query = select(Ticket).where(ticket_visibility_filter(admin))
    if status:
        query = query.where(Ticket.status == status)
    if category_id:
        query = query.where(Ticket.category_id == category_id)
    if overdue:
        query = query.where(overdue_clause())
    if q:
        like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(func.lower(Ticket.ticket_no).like(like, escape="\\")
                            | func.lower(Ticket.description).like(like, escape="\\"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Ticket.created_at.desc()).limit(limit).offset(offset)).all()
    return TicketPage(items=[serializers.list_item(admin, t) for t in rows], total=total, limit=limit, offset=offset)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    s = get_settings()
    now = utcnow()
    age = heartbeat_age_minutes(db, now)
    stale_after = max(5.0, 3 * s.worker_tick_seconds / 60)
    worker_status = "never" if age is None else ("ok" if age <= stale_after else "stale")
    last_run = get_state(db, "scheduler_last_run")

    waiting = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.email_sent.is_(False), Notification.email_attempts < s.email_max_attempts)) or 0
    failed_rows = db.scalars(select(Notification).where(
        Notification.email_sent.is_(False), Notification.email_error.is_not(None),
        Notification.email_attempts >= s.email_max_attempts).order_by(Notification.created_at.desc()).limit(20)).all()
    failed_total = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.email_sent.is_(False), Notification.email_error.is_not(None),
        Notification.email_attempts >= s.email_max_attempts)) or 0
    failures = []
    for n in failed_rows:
        u = db.get(User, n.user_id)
        failures.append({"notification_id": str(n.id), "to": u.email if u else None, "error": n.email_error,
                         "attempts": n.email_attempts, "at": n.created_at.isoformat()})

    uploads = Path(s.upload_dir)
    try:
        uploads.mkdir(parents=True, exist_ok=True)
        writable = os.access(uploads, os.W_OK)
    except OSError:
        writable = False
    return {
        "worker": {
            "status": worker_status,
            "last_heartbeat": get_state(db, HEARTBEAT),
            "minutes_ago": round(age, 1) if age is not None else None,
            "last_run": json.loads(last_run) if last_run else None,
            "last_error": get_state(db, "scheduler_last_error"),
        },
        "email": {"configured": s.email_configured, "waiting": waiting, "gave_up": failed_total,
                  "recent_failures": failures},
        "overdue_tickets": db.scalar(select(func.count()).select_from(Ticket).where(overdue_clause(now))) or 0,
        "checks": {"database": "ok", "uploads_dir_writable": writable, "clamav_enabled": s.clamav_enabled,
                   "dev_login_enabled": s.dev_login_enabled, "watchdog_enabled": s.watchdog_enabled},
    }
