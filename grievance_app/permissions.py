"""The ONE place that decides who may see or act on a ticket.

Every list, detail, attachment download, notification and search must use
these functions. Nobody writes their own check.

Rules
-----
View, normal ticket   : reporter; assignee; anyone in the ticket's routing
                        chain (level 0/1/2); admin.
View, confidential    : reporter; officers who are the assignee or in the chain.
                        Nobody else, including admins.
Handle (start, ask for info, resolve): assignee or chain member (officer only
                        if confidential). Never the reporter of the same ticket.
Escalate / reassign   : normal -> head (level 1 or 2) or admin;
                        confidential -> officer in the chain.
Unauthorised access should look like "not found" (use get_ticket_or_404).
"""
from typing import Callable, Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import and_, exists, false, or_, select, true
from sqlalchemy.orm import Session

from .constants import Role
from .models import Event, Routing, Ticket, User


# ---------- chain helpers ----------

def _chain_level(user_id, ticket: Ticket) -> Optional[int]:
    """Highest level (0, 1, 2) the user holds in the ticket's route, or None."""
    route = ticket.route
    if route is None:
        return None
    found = None
    for level, uid in enumerate((route.level0_user_id, route.level1_user_id, route.level2_user_id)):
        if uid is not None and uid == user_id:
            found = level
    return found


def is_chain_member(user: User, ticket: Ticket) -> bool:
    return _chain_level(user.id, ticket) is not None


def _is_assignee_or_chain(user: User, ticket: Ticket) -> bool:
    return ticket.assignee_id == user.id or is_chain_member(user, ticket)


# ---------- single-ticket checks ----------

def can_view(user: User, ticket: Ticket) -> bool:
    if user.id == ticket.reporter_id:
        return True
    if ticket.confidential:
        return user.role == Role.OFFICER and _is_assignee_or_chain(user, ticket)
    if user.role == Role.ADMIN:
        return True
    return _is_assignee_or_chain(user, ticket)


def can_handle(user: User, ticket: Ticket) -> bool:
    """Start, request info, resolve."""
    if user.id == ticket.reporter_id:        # conflict of interest
        return False
    if ticket.confidential:
        return user.role == Role.OFFICER and _is_assignee_or_chain(user, ticket)
    return _is_assignee_or_chain(user, ticket)


def can_escalate(user: User, ticket: Ticket) -> bool:
    """Manual escalate and reassign."""
    if user.id == ticket.reporter_id:
        return False
    if ticket.confidential:
        return can_handle(user, ticket)
    if user.role == Role.ADMIN:
        return True
    level = _chain_level(user.id, ticket)
    return level is not None and level >= 1


def can_download_attachment(user: User, ticket: Ticket) -> bool:
    return can_view(user, ticket)


# ---------- list filter (same rules, as SQL) ----------

def _in_chain_sql(user_id):
    return exists().where(and_(
        Routing.id == Ticket.route_id,
        or_(Routing.level0_user_id == user_id,
            Routing.level1_user_id == user_id,
            Routing.level2_user_id == user_id),
    ))


def in_chain_filter(user: User):
    """WHERE-clause: tickets whose routing chain contains the user."""
    return _in_chain_sql(user.id)


def ticket_visibility_filter(user: User):
    """WHERE-clause matching exactly the tickets can_view() allows.

    Use: select(Ticket).where(ticket_visibility_filter(user))
    """
    assignee_or_chain = or_(Ticket.assignee_id == user.id, _in_chain_sql(user.id))
    own = Ticket.reporter_id == user.id
    confidential_branch = (and_(Ticket.confidential.is_(True), assignee_or_chain)
                           if user.role == Role.OFFICER else false())
    normal_branch = and_(Ticket.confidential.is_(False),
                         true() if user.role == Role.ADMIN else assignee_or_chain)
    return or_(own, confidential_branch, normal_branch)


# ---------- loading helpers ----------

def get_ticket_or_404(db: Session, user: User, ticket_id,
                      check: Callable[[User, Ticket], bool] = can_view) -> Ticket:
    """Load a ticket; unknown id and "not allowed" look identical (404)."""
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or not check(user, ticket):
        raise HTTPException(status_code=404, detail="Not found")
    return ticket


def visible_events(user: User, ticket: Ticket, events: Iterable[Event]) -> list[Event]:
    """Reporters see only student-visible events; handlers see everything."""
    if user.id == ticket.reporter_id:
        return [e for e in events if e.visible_to_student]
    return list(events)
