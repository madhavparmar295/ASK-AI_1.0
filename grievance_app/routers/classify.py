from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas_tickets import IdName
from ..security import ratelimit
from ..security.deps import get_current_user
from ..services.classifier import classify

router = APIRouter(tags=["classify"])


class ClassifyIn(BaseModel):
    text: str = Field(min_length=3, max_length=5000)


class ClassifyOut(BaseModel):
    suggested: IdName | None
    confidence: str            # high | medium | low | none
    alternatives: list[IdName]
    confidential: bool         # the form pre-ticks the confidential box; the student may keep it ticked
    urgent: bool


@router.post("/classify", response_model=ClassifyOut)
def classify_text(body: ClassifyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Suggest a category while the student types. Suggestions only; the student decides."""
    ratelimit.check(f"classify:{user.id}", get_settings().classify_rate_limit_per_minute)
    return classify(db, body.text)
