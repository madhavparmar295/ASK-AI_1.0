"""All ticket actions (tasks T4, T6, T7). Routers stay thin; the rules live here.

Conventions
  * 404 = the user cannot see the ticket (handled by get_ticket_or_404 in the router)
  * 403 = the user can see it but may not do this action
  * 409 = the action is not allowed in the ticket's current state
  * Every change writes an Event and calls notify().
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import Role, Status, can_transition
from ..models import Category, Event, Feedback, Ticket, Unit, User
from ..permissions import can_escalate, can_handle
from .errors import ServiceError
from .flags import detect_flags
from .notify import notify
from .routing import find_route, first_active_level, next_level


# ---------- time helpers ----------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def overdue_clause(now: Optional[datetime] = None):
    """WHERE-clause for tickets past their deadline (also used by the Stage 3 scheduler)."""
    return and_(Ticket.status.in_(Status.CLOCK_RUNNING), Ticket.due_at < (now or utcnow()))


# ---------- events and status changes ----------

def add_event(db: Session, ticket: Ticket, type_: str, actor: Optional[User], text: Optional[str] = None,
              from_status: Optional[str] = None, to_status: Optional[str] = None,
              visible_to_student: bool = True, now: Optional[datetime] = None) -> Event:
    ev = Event(ticket_id=ticket.id, type=type_, actor_id=actor.id if actor else None, text=text,
               from_status=from_status, to_status=to_status,
               visible_to_student=visible_to_student, created_at=now or utcnow())
    db.add(ev)
    return ev


def _move(db: Session, ticket: Ticket, new_status: str, actor: Optional[User], text: Optional[str],
          now: datetime, visible: bool = True, event_type: str = "status") -> None:
    if not can_transition(ticket.status, new_status):
        raise ServiceError(409, f"This ticket is {ticket.status.lower()} and cannot move to {new_status.lower()}.")
    old = ticket.status
    ticket.status = new_status
    ticket.updated_at = now
    add_event(db, ticket, event_type, actor, text, old, new_status, visible, now)


def _ensure(condition: bool, message: str = "You are not allowed to do this") -> None:
    if not condition:
        raise ServiceError(403, message)


def sla_hours_for(ticket: Ticket) -> int:
    return ticket.route.category.sla_hours if ticket.route is not None else ticket.category.sla_hours


# ---------- create ----------

def _next_ticket_no(db: Session, now: datetime, offset: int = 0) -> str:
    count = db.scalar(select(func.count()).select_from(Ticket)) or 0
    return f"GRV-{now.year}-{count + 1 + offset:06d}"


def create_ticket(db: Session, user: User, data, now: Optional[datetime] = None) -> Ticket:
    now = now or utcnow()
    s = get_settings()

    category = db.get(Category, data.category_id)
    if category is None or not category.active:
        raise ServiceError(422, "Unknown category")
    unit = None
    if data.unit_id is not None:
        unit = db.get(Unit, data.unit_id)
        if unit is None or not unit.active or unit.type != category.unit_type:
            raise ServiceError(422, "This location does not match the category")

    since = now - timedelta(hours=24)
    recent = db.scalar(select(func.count()).select_from(Ticket)
                       .where(Ticket.reporter_id == user.id, Ticket.created_at >= since)) or 0
    if recent >= s.max_tickets_per_day:
        raise ServiceError(429, "Daily limit of new tickets reached. Try again tomorrow.")

    same_unit = Ticket.unit_id.is_(None) if unit is None else Ticket.unit_id == unit.id
    existing = db.scalar(select(Ticket).where(
        Ticket.reporter_id == user.id, Ticket.category_id == category.id, same_unit,
        Ticket.status.in_(Status.OPEN)))
    if existing is not None:
        raise ServiceError(409, "You already have an open ticket for this. Please add details to it instead.",
                           existing_ticket_id=str(existing.id), existing_ticket_no=existing.ticket_no)

    flags = detect_flags(data.description)
    confidential = bool(data.confidential or category.confidential or flags.get("confidential"))
    urgent = bool(flags.get("urgent"))

    choice = find_route(db, category, unit.id if unit else None, confidential)
    sla_hours = choice.route.category.sla_hours

    ticket = None
    for attempt in range(5):
        candidate = Ticket(
            ticket_no=_next_ticket_no(db, now, attempt), reporter_id=user.id, category_id=category.id,
            unit_id=unit.id if unit else None, route_id=choice.route.id,
            location_text=data.location_text, description=data.description,
            status=Status.ASSIGNED, assignee_id=choice.assignee.id, escalation_level=choice.level,
            due_at=now + timedelta(hours=sla_hours), confidential=confidential, urgent=urgent,
            created_at=now, updated_at=now)
        try:
            with db.begin_nested():
                db.add(candidate)
                db.flush()
            ticket = candidate
            break
        except IntegrityError:
            continue
    if ticket is None:
        raise ServiceError(503, "Could not create the ticket. Please try again.")

    add_event(db, ticket, "status", user, "Ticket created", None, Status.ASSIGNED, True, now)
    db.commit()
    notify(db, "created", ticket, actor=user)
    return ticket


# ---------- reporter actions ----------

def _ensure_reporter(user: User, ticket: Ticket) -> None:
    _ensure(user.id == ticket.reporter_id, "Only the person who reported this can do that")


def reply(db: Session, user: User, ticket: Ticket, text: str, now: Optional[datetime] = None) -> Ticket:
    now = now or utcnow()
    _ensure_reporter(user, ticket)
    if ticket.status not in Status.OPEN:
        raise ServiceError(409, "This ticket is not open. Use 'not fixed' if the problem remains.")
    if ticket.status == Status.NEEDS_INFO:
        if ticket.paused_at is not None and ticket.due_at is not None:
            ticket.due_at = aware(ticket.due_at) + (now - aware(ticket.paused_at))   # resume the clock
        ticket.paused_at = None
        _move(db, ticket, Status.IN_PROGRESS, user, text, now, event_type="message")
    else:
        ticket.updated_at = now
        add_event(db, ticket, "message", user, text, visible_to_student=True, now=now)
    db.commit()
    notify(db, "replied", ticket, actor=user)
    return ticket


def cancel(db: Session, user: User, ticket: Ticket, reason: Optional[str] = None,
           now: Optional[datetime] = None) -> Ticket:
    now = now or utcnow()
    _ensure_reporter(user, ticket)
    ticket.paused_at = None
    _move(db, ticket, Status.CANCELLED, user, reason or "Cancelled by the reporter", now)
    db.commit()
    notify(db, "cancelled", ticket, actor=user)
    return ticket


def confirm(db: Session, user: User, ticket: Ticket, now: Optional[datetime] = None) -> Ticket:
    now = now or utcnow()
    _ensure_reporter(user, ticket)
    if ticket.status != Status.RESOLVED:
        raise ServiceError(409, "Only a resolved ticket can be confirmed.")
    _move(db, ticket, Status.CLOSED, user, "Reporter confirmed the fix", now)
    ticket.closed_at = now
    db.commit()
    notify(db, "closed", ticket, actor=user)
    return ticket


def reopen(db: Session, user: User, ticket: Ticket, reason: str, now: Optional[datetime] = None) -> Ticket:
    """Reporter says 'not fixed': back to the first level with a new deadline."""
    now = now or utcnow()
    _ensure_reporter(user, ticket)
    if ticket.status != Status.RESOLVED:
        raise ServiceError(409, "Only a resolved ticket can be reopened.")
    _move(db, ticket, Status.ASSIGNED, user, f"Not fixed: {reason}", now)
    choice = first_active_level(db, ticket.route) if ticket.route is not None else None
    if choice is not None:
        ticket.escalation_level, user_obj = choice
        ticket.assignee_id = user_obj.id
    else:
        ticket.escalation_level = 0
    ticket.due_at = now + timedelta(hours=sla_hours_for(ticket))
    ticket.resolved_at = None
    db.commit()
    notify(db, "reopened", ticket, actor=user)
    return ticket


def give_feedback(db: Session, user: User, ticket: Ticket, rating: int, comment: Optional[str],
                  now: Optional[datetime] = None) -> Feedback:
    now = now or utcnow()
    _ensure_reporter(user, ticket)
    if ticket.status != Status.CLOSED:
        raise ServiceError(409, "Feedback can be given after the ticket is closed.")
    if db.get(Feedback, ticket.id) is not None:
        raise ServiceError(409, "Feedback was already given for this ticket.")
    fb = Feedback(ticket_id=ticket.id, rating=rating, comment=comment, created_at=now)
    db.add(fb)
    add_event(db, ticket, "feedback", user, f"Feedback: {rating}/5", visible_to_student=True, now=now)
    db.commit()
    return fb


# ---------- handler actions ----------

def _ensure_handler(user: User, ticket: Ticket) -> None:
    _ensure(can_handle(user, ticket), "You cannot work on this ticket")


def start(db: Session, user: User, ticket: Ticket, now: Optional[datetime] = None) -> Ticket:
    now = now or utcnow()
    _ensure_handler(user, ticket)
    text = "Work started"
    if ticket.assignee_id != user.id:
        ticket.assignee_id = user.id
        text = f"Work started by {user.name}"
    _move(db, ticket, Status.IN_PROGRESS, user, text, now)
    db.commit()
    return ticket


def request_info(db: Session, user: User, ticket: Ticket, text: str, now: Optional[datetime] = None) -> Ticket:
    """Ask the reporter for more information. The deadline clock pauses."""
    now = now or utcnow()
    _ensure_handler(user, ticket)
    _move(db, ticket, Status.NEEDS_INFO, user, text, now)
    ticket.paused_at = now
    db.commit()
    notify(db, "info_requested", ticket, actor=user)
    return ticket


def resolve(db: Session, user: User, ticket: Ticket, note: str, now: Optional[datetime] = None) -> Ticket:
    now = now or utcnow()
    _ensure_handler(user, ticket)
    _move(db, ticket, Status.RESOLVED, user, note, now)
    ticket.resolved_at = now
    db.commit()
    notify(db, "resolved", ticket, actor=user)
    return ticket


def escalate_ticket(db: Session, ticket: Ticket, actor: Optional[User], reason: str,
                    now: Optional[datetime] = None) -> Ticket:
    """Move to the next level. actor=None means the scheduler did it (Stage 3).

    No permission check here; use escalate() for people.
    """
    now = now or utcnow()
    nxt = next_level(db, ticket.route, ticket.escalation_level, officers_only=ticket.confidential)
    if nxt is None:
        raise ServiceError(409, "There is no higher level configured for this ticket.")
    level, new_user = nxt
    previous = ticket.assignee_id
    _move(db, ticket, Status.ESCALATED, actor, f"Escalated to {new_user.name}. {reason}", now)
    ticket.escalation_level = level
    ticket.assignee_id = new_user.id
    ticket.due_at = now + timedelta(hours=sla_hours_for(ticket))
    ticket.paused_at = None
    db.commit()
    notify(db, "escalated", ticket, actor=actor, previous_assignee_id=previous)
    return ticket


def escalate(db: Session, user: User, ticket: Ticket, reason: str, now: Optional[datetime] = None) -> Ticket:
    _ensure(can_escalate(user, ticket), "You cannot escalate this ticket")
    return escalate_ticket(db, ticket, user, f"Reason: {reason}", now)


def reassign(db: Session, user: User, ticket: Ticket, new_assignee_id, reason: str,
             now: Optional[datetime] = None) -> Ticket:
    now = now or utcnow()
    _ensure(can_escalate(user, ticket), "You cannot reassign this ticket")
    if ticket.status not in Status.CLOCK_RUNNING:
        raise ServiceError(409, "Only a ticket that is waiting for work can be reassigned.")
    new = db.get(User, new_assignee_id)
    if new is None or not new.active or new.role not in (Role.STAFF, Role.OFFICER):
        raise ServiceError(422, "Choose an active staff member")
    if ticket.confidential and new.role != Role.OFFICER:
        raise ServiceError(422, "Confidential tickets can only go to designated officers")
    if new.id == ticket.assignee_id:
        raise ServiceError(422, "That person already has this ticket")
    if new.id == ticket.reporter_id:
        raise ServiceError(422, "A ticket cannot be assigned to the person who reported it")
    old = db.get(User, ticket.assignee_id) if ticket.assignee_id else None
    ticket.assignee_id = new.id
    ticket.due_at = now + timedelta(hours=sla_hours_for(ticket))
    ticket.updated_at = now
    add_event(db, ticket, "assignment", user,
              f"Reassigned from {old.name if old else 'nobody'} to {new.name}. Reason: {reason}",
              visible_to_student=False, now=now)
    db.commit()
    notify(db, "reassigned", ticket, actor=user, previous_assignee_id=old.id if old else None)
    return ticket


# ---------- automatic closing (called by the Stage 3 scheduler) ----------

def auto_close(db: Session, now: Optional[datetime] = None) -> int:
    """Close resolved tickets nobody contested and info requests nobody answered.

    Confidential tickets are never closed automatically. Returns how many were closed.
    """
    now = now or utcnow()
    s = get_settings()
    resolved_cut = now - timedelta(days=s.auto_close_resolved_days)
    info_cut = now - timedelta(days=s.auto_close_needs_info_days)
    candidates = db.scalars(select(Ticket).where(
        Ticket.confidential.is_(False),
        ((Ticket.status == Status.RESOLVED) & (Ticket.resolved_at < resolved_cut)) |
        ((Ticket.status == Status.NEEDS_INFO) & (Ticket.paused_at < info_cut)))).all()
    for t in candidates:
        reason = ("Closed automatically: no objection after the fix"
                  if t.status == Status.RESOLVED else "Closed automatically: no reply to the information request")
        _move(db, t, Status.CLOSED, None, reason, now)
        t.closed_at = now
        t.paused_at = None
        db.commit()
        notify(db, "closed", t, actor=None)
    return len(candidates)


# ---------- what the current user may do (the UI shows buttons from this) ----------

def available_actions(db: Session, user: User, ticket: Ticket) -> list[str]:
    actions: list[str] = []
    st = ticket.status
    if user.id == ticket.reporter_id:
        if st in Status.OPEN:
            actions += ["reply", "cancel", "upload"]
        if st == Status.RESOLVED:
            actions += ["confirm", "reopen"]
        if st == Status.CLOSED and db.get(Feedback, ticket.id) is None:
            actions.append("feedback")
    if can_handle(user, ticket) and user.id != ticket.reporter_id:
        if st in (Status.ASSIGNED, Status.ESCALATED):
            actions.append("start")
        if st in Status.CLOCK_RUNNING:
            actions += ["request_info", "resolve"]
        if st in Status.OPEN and "upload" not in actions:
            actions.append("upload")
    if can_escalate(user, ticket) and st in Status.CLOCK_RUNNING:
        if next_level(db, ticket.route, ticket.escalation_level, officers_only=ticket.confidential) is not None:
            actions.append("escalate")
        actions.append("reassign")
    return actions
