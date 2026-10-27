"""The background jobs (task T8): escalate overdue tickets, auto-close, send queued emails.

Everything here is safe to run twice at the same time (two workers, a restart, a manual run):
escalation uses a conditional UPDATE and emails are claimed before sending.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import Status
from ..models import Event, Notification, Ticket, User
from .email import Sender, smtp_send
from .notify import notify
from .routing import next_level
from .state import get_state, get_state_row, set_state
from .tickets import add_event, aware, auto_close, overdue_clause, sla_hours_for, utcnow

log = logging.getLogger("grievance.scheduler")
HEARTBEAT = "scheduler_heartbeat"


# ---------- escalation ----------

def escalate_if_overdue(db: Session, ticket_id, now: datetime) -> str:
    """Escalate one overdue ticket. Returns 'escalated', 'top_level' or 'skipped'."""
    t = db.get(Ticket, ticket_id)
    if t is None or t.status not in Status.CLOCK_RUNNING or t.due_at is None or aware(t.due_at) >= now:
        return "skipped"
    old_status, old_level, previous = t.status, t.escalation_level, t.assignee_id
    due_before = t.due_at
    nxt = next_level(db, t.route, old_level, officers_only=t.confidential)

    if nxt is None:
        # Nobody higher. Record it once per missed deadline; the ticket stays overdue and visible.
        already = db.scalar(select(Event.id).where(Event.ticket_id == t.id, Event.type == "overdue_top",
                                                   Event.created_at >= due_before))
        if already:
            return "skipped"
        add_event(db, t, "overdue_top", None, "Deadline missed and there is no higher level to escalate to.",
                  visible_to_student=False, now=now)
        db.commit()
        notify(db, "overdue_top", t)
        return "top_level"

    level, user = nxt
    claimed = db.execute(
        update(Ticket)
        .where(Ticket.id == t.id, Ticket.escalation_level == old_level,
               Ticket.status.in_(Status.CLOCK_RUNNING), Ticket.due_at < now)
        .values(status=Status.ESCALATED, escalation_level=level, assignee_id=user.id,
                due_at=now + timedelta(hours=sla_hours_for(t)), paused_at=None, updated_at=now)
        .execution_options(synchronize_session=False)      # the database decides, not Python
    ).rowcount
    if claimed != 1:
        db.rollback()
        return "skipped"                # someone else escalated it first
    db.expire(t)
    add_event(db, t, "status", None, f"Deadline missed. Escalated automatically to {user.name}.",
              old_status, Status.ESCALATED, True, now)
    db.commit()
    db.refresh(t)
    notify(db, "escalated", t, actor=None, previous_assignee_id=previous)
    return "escalated"


def run_escalations(db: Session, now: Optional[datetime] = None, batch: int = 500) -> int:
    now = now or utcnow()
    ids = db.scalars(select(Ticket.id).where(overdue_clause(now)).order_by(Ticket.due_at).limit(batch)).all()
    return sum(1 for tid in ids if escalate_if_overdue(db, tid, now) == "escalated")


# ---------- email outbox ----------

def _body(db: Session, n: Notification, user: User):
    ticket = db.get(Ticket, n.ticket_id) if n.ticket_id else None
    base = get_settings().app_base_url.rstrip("/")
    link = f"{base}/grievance/issues/{n.ticket_id}" if n.ticket_id else f"{base}/grievance"
    if ticket is None or ticket.confidential:
        subject = "Grievance system: update available"
    else:
        subject = f"Ticket {ticket.ticket_no}"
    return subject, f"Hello {user.name},\n\n{n.text}\n\nOpen: {link}\n\n-- College Grievance System"


def process_email_outbox(db: Session, now: Optional[datetime] = None, sender: Optional[Sender] = None,
                         limit: int = 100) -> dict:
    """Send queued emails. Failures are recorded on the notification and retried later."""
    now = now or utcnow()
    s = get_settings()
    if not s.email_configured:
        # Nothing can be sent. Give up on queued mails instead of flooding the inbox later.
        gave_up = db.execute(update(Notification)
                             .where(Notification.email_sent.is_(False), Notification.email_attempts < s.email_max_attempts)
                             .values(email_attempts=s.email_max_attempts, email_error="Email is not configured")
                             .execution_options(synchronize_session=False)).rowcount
        db.commit()
        return {"sent": 0, "failed": 0, "gave_up": gave_up}
    sender = sender or smtp_send
    retry_before = now - timedelta(minutes=s.email_retry_minutes)
    pending = db.scalars(select(Notification).where(
        Notification.email_sent.is_(False), Notification.email_attempts < s.email_max_attempts,
        (Notification.email_last_attempt_at.is_(None)) | (Notification.email_last_attempt_at < retry_before))
        .order_by(Notification.created_at).limit(limit)).all()
    sent = failed = 0
    for n in pending:
        # Claim the row so a second worker does not send the same email.
        claimed = db.execute(update(Notification).where(
            Notification.id == n.id, Notification.email_sent.is_(False),
            Notification.email_attempts == n.email_attempts)
            .values(email_attempts=n.email_attempts + 1, email_last_attempt_at=now)
            .execution_options(synchronize_session=False)).rowcount
        db.commit()
        db.expire(n)
        if claimed != 1:
            continue
        user = db.get(User, n.user_id)
        try:
            if user is None or not user.email:
                raise ValueError("No email address for this user")
            subject, body = _body(db, n, user)
            sender(user.email, subject, body)
            db.execute(update(Notification).where(Notification.id == n.id).values(email_sent=True, email_error=None)
                       .execution_options(synchronize_session=False))
            sent += 1
        except Exception as exc:      # record every failure; never let one bad mail stop the rest
            db.execute(update(Notification).where(Notification.id == n.id).values(email_error=str(exc)[:500])
                       .execution_options(synchronize_session=False))
            failed += 1
            log.warning("Email to notification %s failed: %s", n.id, type(exc).__name__)
        db.commit()
    return {"sent": sent, "failed": failed}


# ---------- one worker pass ----------

def run_once(db: Session, now: Optional[datetime] = None, sender: Optional[Sender] = None) -> dict:
    """All jobs once. A failure in one job never stops the others. Records a heartbeat."""
    now = now or utcnow()
    summary: dict = {}
    jobs = (("escalated", lambda: run_escalations(db, now)),
            ("auto_closed", lambda: auto_close(db, now)),
            ("emails", lambda: process_email_outbox(db, now, sender)))
    for name, job in jobs:
        try:
            summary[name] = job()
        except Exception as exc:
            db.rollback()
            summary[name] = "error"
            set_state(db, "scheduler_last_error", f"{name}: {type(exc).__name__}: {str(exc)[:300]}", now)
            log.exception("Worker job %s failed", name)
    set_state(db, "scheduler_last_run", json.dumps(summary), now)
    set_state(db, HEARTBEAT, now.isoformat(), now)
    return summary


# ---------- watchdog (runs inside the API process, so it can notice a dead worker) ----------

def heartbeat_age_minutes(db: Session, now: datetime) -> Optional[float]:
    raw = get_state(db, HEARTBEAT)
    if not raw:
        return None
    return (now - aware(datetime.fromisoformat(raw))).total_seconds() / 60


def check_heartbeat(db: Session, now: Optional[datetime] = None, sender: Optional[Sender] = None) -> bool:
    """Email the admin once per outage if the worker has not run recently. Returns True if alerted."""
    now = now or utcnow()
    s = get_settings()
    if get_state(db, "watchdog_started_at") is None:
        set_state(db, "watchdog_started_at", now.isoformat(), now)
    age = heartbeat_age_minutes(db, now)
    if age is None:   # never ran: measure from when we started watching
        age = (now - aware(datetime.fromisoformat(get_state(db, "watchdog_started_at")))).total_seconds() / 60
    if age < s.heartbeat_alert_minutes:
        return False
    last_alert = get_state(db, "watchdog_alerted_at")
    beat = get_state(db, HEARTBEAT)
    if last_alert and (not beat or aware(datetime.fromisoformat(last_alert)) > aware(datetime.fromisoformat(beat))):
        return False                      # already alerted for this outage
    if not s.email_configured:
        set_state(db, "watchdog_alerted_at", now.isoformat(), now)
        log.error("Worker has not run for %d minutes and email is not configured", int(age))
        return False
    to = [s.admin_alert_email] if s.admin_alert_email else [
        u.email for u in db.scalars(select(User).where(User.role == "admin", User.active.is_(True))).all()]
    send = sender or smtp_send
    ok = False
    for addr in to:
        try:
            send(addr, "Grievance system: background worker is not running",
                 f"The background worker has not run for about {int(age)} minutes. Escalations, automatic closing and "
                 f"emails are paused. Restart it (see the runbook).")
            ok = True
        except Exception:
            log.exception("Could not send the watchdog alert to %s", addr)
    if ok:
        set_state(db, "watchdog_alerted_at", now.isoformat(), now)
    return ok
