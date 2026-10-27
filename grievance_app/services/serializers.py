"""Turns tickets into API responses, applying what each viewer may see."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attachment, Event, Feedback, Ticket, User
from ..permissions import visible_events
from ..schemas_tickets import (AttachmentOut, EventOut, FeedbackOut, IdName,
                               ReporterOut, TicketDetail, TicketListItem)
from .tickets import aware, available_actions, utcnow
from ..constants import Status


def _is_overdue(t: Ticket) -> bool:
    return bool(t.status in Status.CLOCK_RUNNING and t.due_at is not None and aware(t.due_at) < utcnow())


def _assignee(viewer: User, t: Ticket) -> Optional[IdName]:
    if t.assignee is None:
        return None
    if t.confidential and viewer.id == t.reporter_id:
        return None   # reporters of confidential tickets are not shown who handles them
    return IdName(id=t.assignee.id, name=t.assignee.name)


def list_item(viewer: User, t: Ticket) -> TicketListItem:
    staff_view = viewer.id != t.reporter_id
    title = t.description if len(t.description) <= 80 else t.description[:77] + "..."
    return TicketListItem(
        id=t.id, ticket_no=t.ticket_no, status=t.status, title=title,
        category=IdName(id=t.category.id, name=t.category.name),
        unit=IdName(id=t.unit.id, name=t.unit.name) if t.unit else None,
        assignee=_assignee(viewer, t),
        reporter_name=t.reporter.name if staff_view else None,
        escalation_level=t.escalation_level, due_at=t.due_at, overdue=_is_overdue(t),
        confidential=t.confidential, urgent=t.urgent, created_at=t.created_at)


def _actor_label(db: Session, viewer: User, t: Ticket, e: Event) -> str:
    if e.actor_id is None:
        return "System"
    if e.actor_id == viewer.id:
        return "You"
    if t.confidential and viewer.id == t.reporter_id:
        return "Designated officer"
    actor = db.get(User, e.actor_id)
    return actor.name if actor else "Unknown"


def detail(db: Session, viewer: User, t: Ticket) -> TicketDetail:
    is_reporter = viewer.id == t.reporter_id
    events = db.scalars(select(Event).where(Event.ticket_id == t.id).order_by(Event.created_at, Event.id)).all()
    shown = visible_events(viewer, t, events)
    atts = db.scalars(select(Attachment).where(Attachment.ticket_id == t.id).order_by(Attachment.created_at)).all()
    fb = db.get(Feedback, t.id)
    reporter = None
    if not is_reporter:
        r = t.reporter
        reporter = ReporterOut(id=r.id, name=r.name, email=r.email, department=r.department,
                               hostel=r.hostel, room=r.room)
    return TicketDetail(
        id=t.id, ticket_no=t.ticket_no, status=t.status,
        category=IdName(id=t.category.id, name=t.category.name),
        unit=IdName(id=t.unit.id, name=t.unit.name) if t.unit else None,
        location_text=t.location_text, description=t.description, confidential=t.confidential,
        urgent=t.urgent, escalation_level=t.escalation_level, due_at=t.due_at, overdue=_is_overdue(t),
        assignee=_assignee(viewer, t), reporter=reporter, created_at=t.created_at,
        updated_at=t.updated_at, resolved_at=t.resolved_at, closed_at=t.closed_at,
        attachments=[AttachmentOut(id=a.id, original_name=a.original_name, mime_type=a.mime_type,
                                   size_bytes=a.size_bytes, scan_status=a.scan_status,
                                   uploaded_by_me=a.uploaded_by == viewer.id, created_at=a.created_at)
                     for a in atts],
        events=[EventOut(type=e.type, from_status=e.from_status, to_status=e.to_status, text=e.text,
                         actor=_actor_label(db, viewer, t, e), created_at=e.created_at,
                         internal=None if is_reporter else (not e.visible_to_student))
                for e in shown],
        actions=available_actions(db, viewer, t),
        feedback=FeedbackOut(rating=fb.rating, comment=fb.comment) if fb else None)
