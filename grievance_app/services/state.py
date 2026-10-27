from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import SystemState, utcnow


def get_state(db: Session, key: str) -> Optional[str]:
    row = db.get(SystemState, key)
    return row.value if row else None


def get_state_row(db: Session, key: str) -> Optional[SystemState]:
    return db.get(SystemState, key)


def set_state(db: Session, key: str, value: Optional[str], now: Optional[datetime] = None) -> None:
    row = db.get(SystemState, key)
    if row is None:
        db.add(SystemState(key=key, value=value, updated_at=now or utcnow()))
    else:
        row.value = value
        row.updated_at = now or utcnow()
    db.commit()
