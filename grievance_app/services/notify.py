"""Notifications (task T9).

notify() is called by the ticket actions AFTER the ticket change is saved. It writes in-app notifications
and queues emails (the worker sends them). It must never break the ticket action: any error is logged.

Confidential tickets are content-free everywhere: no ticket number, category or text, only
"there is an update, log in". Urgent tickets get an [URGENT] prefix.

kind            who is told
created         reporter ("received"), assignee ("assigned")
reassigned      new assignee
info_requested  reporter
replied         assignee
escalated       new assignee, previous assignee, reporter
resolved        reporter (confirm or reopen)
closed          reporter (feedback link)
cancelled       assignee
reopened        new assignee
overdue_top     assignee (deadline missed and nobody higher is configured)
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Notification, Ticket, User

log = logging.getLogger("grievance.notify")

GENERIC_REPORTER = "There is an update on your ticket. Log in to view it."
GENERIC_STAFF = "A restricted ticket needs your attention. Log in to view it."

REPORTER_TEXT = {
    "created": "We received your problem. Your ticket number is {no}.",
    "info_requested": "More information is needed on ticket {no}. Please reply.",
    "escalated": "Ticket {no} was passed to a senior person because it was taking too long.",
    "resolved": "Ticket {no} was marked as resolved. Please confirm, or tell us if it is not fixed.",
    "closed": "Ticket {no} is closed. Please tell us how we did.",
}
STAFF_TEXT = {
    "created": "New ticket {no} ({category}) is assigned to you.",
    "reassigned": "Ticket {no} ({category}) was assigned to you.",
    "replied": "The reporter replied on ticket {no}.",
    "escalated": "Ticket {no} ({category}) was escalated to you.",
    "cancelled": "Ticket {no} was cancelled by the reporter.",
    "reopened": "Ticket {no} was reopened: the reporter says it is not fixed.",
    "overdue_top": "Ticket {no} is past its deadline and there is nobody higher to escalate to.",
}
PREVIOUS_TEXT = "Ticket {no} was escalated to {name} because the deadline passed."


def _recipients(db: Session, kind: str, ticket: Ticket, actor: Optional[User], previous_id):
    """List of (user, audience, text_template, extra) with duplicates removed."""
    out, seen = [], set()

    def add(user, audience, template, **extra):
        if user is None or not user.active or user.id in seen:
            return
        if actor is not None and user.id == actor.id and kind not in ("created", "closed"):
            return                      # do not notify people about their own actions
        seen.add(user.id)
        out.append((user, audience, template, extra))

    reporter = ticket.reporter
    assignee = ticket.assignee
    if kind in REPORTER_TEXT:
        add(reporter, "reporter", REPORTER_TEXT[kind])
    if kind in STAFF_TEXT:
        add(assignee, "staff", STAFF_TEXT[kind])
    if kind == "escalated" and previous_id is not None and previous_id != ticket.assignee_id:
        add(db.get(User, previous_id), "staff", PREVIOUS_TEXT, name=assignee.name if assignee else "a senior person")
    return out


def _render(ticket: Ticket, audience: str, template: str, extra: dict) -> str:
    if ticket.confidential:
        return GENERIC_REPORTER if audience == "reporter" else GENERIC_STAFF
    text = template.format(no=ticket.ticket_no, category=ticket.category.name, **extra)
    return f"[URGENT] {text}" if ticket.urgent else text


def notify(db: Session, kind: str, ticket: Ticket, *, actor: Optional[User] = None,
           previous_assignee_id=None) -> None:
    try:
        rows = _recipients(db, kind, ticket, actor, previous_assignee_id)
        for user, audience, template, extra in rows:
            db.add(Notification(user_id=user.id, ticket_id=ticket.id,
                                text=_render(ticket, audience, template, extra)))
        if rows:
            db.commit()
    except Exception:
        db.rollback()
        log.exception("Could not create notifications (kind=%s, ticket=%s)", kind, getattr(ticket, "id", None))
