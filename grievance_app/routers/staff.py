from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..constants import Role, Status
from ..db import get_db
from ..models import Ticket, User
from ..permissions import in_chain_filter, ticket_visibility_filter
from ..schemas_tickets import TicketPage
from ..security.deps import require_role
from ..services import serializers
from ..services.errors import ServiceError
from ..services.tickets import overdue_clause

router = APIRouter(prefix="/staff", tags=["staff"])
staff_only = require_role(Role.STAFF, Role.OFFICER)    # others get 404


def _page(db: Session, user: User, scope: str, status: Optional[str], overdue: bool,
          limit: int, offset: int) -> TicketPage:
    if status is not None and status not in Status.ALL:
        raise ServiceError(422, "Unknown status")
    q = select(Ticket).where(ticket_visibility_filter(user), Ticket.reporter_id != user.id)
    if scope == "mine":
        q = q.where(Ticket.assignee_id == user.id)
    else:   # team: my own plus everything in tickets whose chain includes me
        q = q.where(or_(Ticket.assignee_id == user.id, in_chain_filter(user)))
    if status:
        q = q.where(Ticket.status == status)
    if overdue:
        q = q.where(overdue_clause())
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Ticket.due_at.asc().nulls_last(), Ticket.created_at)
                      .limit(limit).offset(offset)).all()
    return TicketPage(items=[serializers.list_item(user, t) for t in rows], total=total,
                      limit=limit, offset=offset)


@router.get("/issues", response_model=TicketPage)
def queue(scope: Literal["mine", "team"] = "mine", status: Optional[str] = None, overdue: bool = False,
          limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
          user: User = Depends(staff_only), db: Session = Depends(get_db)):
    """My queue (assigned to me) or the team view (tickets whose chain includes me)."""
    return _page(db, user, scope, status, overdue, limit, offset)


@router.get("/overdue", response_model=TicketPage)
def overdue_list(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 user: User = Depends(staff_only), db: Session = Depends(get_db)):
    """Overdue tickets in my chain (what heads watch)."""
    return _page(db, user, "team", None, True, limit, offset)
