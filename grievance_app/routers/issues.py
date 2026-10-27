import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constants import Role, Status
from ..db import get_db
from ..models import Ticket, User
from ..permissions import can_escalate, get_ticket_or_404
from ..schemas_tickets import (FeedbackOut, FeedbackIn, IssueCreate, NoteIn, OptionalReasonIn,
                               ReasonIn, ReassignIn, TextIn, TicketDetail, TicketPage)
from ..security.deps import get_current_user
from ..services import serializers, tickets
from ..services.errors import ServiceError

router = APIRouter(tags=["issues"])


class PersonOption(BaseModel):
    id: uuid.UUID
    name: str
    role: str


def _load(db: Session, user: User, ticket_id: uuid.UUID) -> Ticket:
    return get_ticket_or_404(db, user, ticket_id)       # 404 if the user cannot see it


@router.post("/issues", response_model=TicketDetail, status_code=201)
def create_issue(body: IssueCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = tickets.create_ticket(db, user, body)
    return serializers.detail(db, user, t)


@router.get("/issues/mine", response_model=TicketPage)    # must stay above /issues/{ticket_id}
def my_issues(status: Optional[str] = None, limit: int = Query(20, ge=1, le=100),
              offset: int = Query(0, ge=0), user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    if status is not None and status not in Status.ALL:
        raise ServiceError(422, "Unknown status")
    q = select(Ticket).where(Ticket.reporter_id == user.id)
    if status:
        q = q.where(Ticket.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Ticket.created_at.desc()).limit(limit).offset(offset)).all()
    return TicketPage(items=[serializers.list_item(user, t) for t in rows], total=total,
                      limit=limit, offset=offset)


@router.get("/issues/{ticket_id}", response_model=TicketDetail)
def get_issue(ticket_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return serializers.detail(db, user, _load(db, user, ticket_id))


# ---------- reporter actions ----------

@router.post("/issues/{ticket_id}/reply", response_model=TicketDetail)
def reply(ticket_id: uuid.UUID, body: TextIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = tickets.reply(db, user, _load(db, user, ticket_id), body.text)
    return serializers.detail(db, user, t)


@router.post("/issues/{ticket_id}/cancel", response_model=TicketDetail)
def cancel(ticket_id: uuid.UUID, body: OptionalReasonIn = OptionalReasonIn(),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = tickets.cancel(db, user, _load(db, user, ticket_id), body.reason)
    return serializers.detail(db, user, t)


@router.post("/issues/{ticket_id}/confirm", response_model=TicketDetail)
def confirm(ticket_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return serializers.detail(db, user, tickets.confirm(db, user, _load(db, user, ticket_id)))


@router.post("/issues/{ticket_id}/reopen", response_model=TicketDetail)
def reopen(ticket_id: uuid.UUID, body: ReasonIn, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    return serializers.detail(db, user, tickets.reopen(db, user, _load(db, user, ticket_id), body.reason))


@router.post("/issues/{ticket_id}/feedback", response_model=FeedbackOut, status_code=201)
def feedback(ticket_id: uuid.UUID, body: FeedbackIn, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    fb = tickets.give_feedback(db, user, _load(db, user, ticket_id), body.rating, body.comment)
    return FeedbackOut(rating=fb.rating, comment=fb.comment)


# ---------- handler actions (checked inside the service: 403 if not allowed) ----------

@router.post("/issues/{ticket_id}/start", response_model=TicketDetail)
def start(ticket_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return serializers.detail(db, user, tickets.start(db, user, _load(db, user, ticket_id)))


@router.post("/issues/{ticket_id}/request-info", response_model=TicketDetail)
def request_info(ticket_id: uuid.UUID, body: TextIn, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    return serializers.detail(db, user, tickets.request_info(db, user, _load(db, user, ticket_id), body.text))


@router.post("/issues/{ticket_id}/resolve", response_model=TicketDetail)
def resolve(ticket_id: uuid.UUID, body: NoteIn, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    return serializers.detail(db, user, tickets.resolve(db, user, _load(db, user, ticket_id), body.note))


@router.post("/issues/{ticket_id}/escalate", response_model=TicketDetail)
def escalate(ticket_id: uuid.UUID, body: ReasonIn, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    return serializers.detail(db, user, tickets.escalate(db, user, _load(db, user, ticket_id), body.reason))


@router.post("/issues/{ticket_id}/reassign", response_model=TicketDetail)
def reassign(ticket_id: uuid.UUID, body: ReassignIn, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    t = tickets.reassign(db, user, _load(db, user, ticket_id), body.assignee_id, body.reason)
    return serializers.detail(db, user, t)


@router.get("/issues/{ticket_id}/reassign-options", response_model=list[PersonOption])
def reassign_options(ticket_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Who this ticket can be reassigned to (only for people allowed to reassign it)."""
    t = _load(db, user, ticket_id)
    if not can_escalate(user, t):
        raise ServiceError(403, "You cannot reassign this ticket")
    q = select(User).where(User.active.is_(True), User.role.in_((Role.STAFF, Role.OFFICER)),
                           User.id != t.reporter_id)
    if t.assignee_id:
        q = q.where(User.id != t.assignee_id)
    if t.confidential:
        q = q.where(User.role == Role.OFFICER)
    return [PersonOption(id=u.id, name=u.name, role=u.role) for u in db.scalars(q.order_by(User.name)).all()]
