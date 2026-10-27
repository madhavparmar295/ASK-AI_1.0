"""Small read-only lists the screens need to build their forms."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, Unit, User
from ..security.deps import get_current_user

router = APIRouter(prefix="/meta", tags=["meta"])


class CategoryOption(BaseModel):
    id: uuid.UUID
    name: str
    unit_type: str          # which kind of location the form should ask for (campus = none)
    confidential: bool


class UnitOption(BaseModel):
    id: uuid.UUID
    type: str
    name: str


class FormOptions(BaseModel):
    categories: list[CategoryOption]
    units: list[UnitOption]


@router.get("/form-options", response_model=FormOptions)
def form_options(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Active categories and locations for the report form (any signed-in user)."""
    cats = db.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.name)).all()
    units = db.scalars(select(Unit).where(Unit.active.is_(True)).order_by(Unit.type, Unit.name)).all()
    return FormOptions(
        categories=[CategoryOption(id=c.id, name=c.name, unit_type=c.unit_type, confidential=c.confidential) for c in cats],
        units=[UnitOption(id=u.id, type=u.type, name=u.name) for u in units])
