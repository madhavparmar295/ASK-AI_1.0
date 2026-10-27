from typing import Optional

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def audit(db: Session, actor: Optional[User], action: str, entity: str, entity_id=None, detail: str = "") -> None:
    """Record an admin change. Committed together with the change itself by the caller."""
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, entity=entity,
                    entity_id=str(entity_id) if entity_id is not None else None, detail=detail[:2000]))
