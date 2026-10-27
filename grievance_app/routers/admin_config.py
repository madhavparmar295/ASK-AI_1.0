"""Admin configuration API (task T14, API half): categories, units, routing, users, audit log.

Every endpoint here is admin-only (others get 404) and every change is written to the audit log.
"""
import re
import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import FALLBACK_CATEGORY, Role, UnitType
from ..db import get_db
from ..models import AuditLog, Category, Routing, Ticket, Unit, User
from ..security.deps import require_role
from ..services.audit import audit
from ..services.csv_import import read_csv
from ..services.errors import ServiceError

admin_only = require_role(Role.ADMIN)
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_only)])

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")
STAFF_ROLES = (Role.STAFF, Role.OFFICER)


def _conflict(msg: str):
    return ServiceError(409, msg)


# =============================== categories ===============================

class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    confidential: bool = False
    sla_hours: int = Field(default=72, ge=1, le=2160)
    unit_type: Literal["hostel", "department", "building", "mess", "campus"] = "campus"
    keywords: Optional[str] = Field(default=None, max_length=5000)
    active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class CategoryPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    confidential: Optional[bool] = None
    sla_hours: Optional[int] = Field(default=None, ge=1, le=2160)
    unit_type: Optional[Literal["hostel", "department", "building", "mess", "campus"]] = None
    keywords: Optional[str] = Field(default=None, max_length=5000)
    active: Optional[bool] = None


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    confidential: bool
    sla_hours: int
    unit_type: str
    keywords: Optional[str]
    active: bool


def _has_confidential_route(db: Session, exclude_id=None, force_conf=None, force_active=None) -> bool:
    """True if at least one active confidential category has a default route (needed for routing)."""
    for c in db.scalars(select(Category)).all():
        conf = c.confidential if not (exclude_id and c.id == exclude_id and force_conf is not None) else force_conf
        act = c.active if not (exclude_id and c.id == exclude_id and force_active is not None) else force_active
        if conf and act and db.scalar(select(Routing.id).where(Routing.category_id == c.id, Routing.unit_id.is_(None))):
            return True
    return False


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.name)).all()


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    if db.scalar(select(Category.id).where(func.lower(Category.name) == body.name.lower())):
        raise _conflict("A category with this name already exists")
    c = Category(**body.model_dump())
    db.add(c)
    db.flush()
    audit(db, admin, "create", "category", c.id, f"{c.name} (confidential={c.confidential}, sla={c.sla_hours}h)")
    db.commit()
    return c


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(category_id: uuid.UUID, body: CategoryPatch, admin: User = Depends(admin_only),
                    db: Session = Depends(get_db)):
    c = db.get(Category, category_id)
    if c is None:
        raise ServiceError(404, "Not found")
    changes = body.model_dump(exclude_unset=True)
    if c.name == FALLBACK_CATEGORY:
        if changes.get("name", c.name) != c.name or changes.get("active") is False or changes.get("confidential"):
            raise _conflict(f'"{FALLBACK_CATEGORY}" is the fallback category: it cannot be renamed, deactivated or made confidential')
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        other = db.scalar(select(Category.id).where(func.lower(Category.name) == changes["name"].lower(),
                                                    Category.id != c.id))
        if other:
            raise _conflict("A category with this name already exists")
    if "unit_type" in changes and changes["unit_type"] != c.unit_type:
        clash = db.scalar(select(Routing.id).join(Unit, Routing.unit_id == Unit.id)
                          .where(Routing.category_id == c.id, Unit.type != changes["unit_type"]))
        if clash:
            raise _conflict("Some routes of this category use locations of the old type. Delete or change them first.")
    if c.confidential and (changes.get("confidential") is False or changes.get("active") is False):
        if not _has_confidential_route(db, c.id, changes.get("confidential", c.confidential), changes.get("active", c.active)):
            raise _conflict("At least one active confidential category with a default route must remain")
    if changes.get("confidential") is True and c.name != FALLBACK_CATEGORY:
        pass   # allowed; its route must then contain only officers (checked when routes are saved)
    for k, v in changes.items():
        setattr(c, k, v)
    audit(db, admin, "update", "category", c.id, f"{c.name}: {sorted(changes)}")
    db.commit()
    return c


# =============================== units ===============================

class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    type: Literal["hostel", "department", "building", "mess", "campus"]

    @field_validator("name")
    @classmethod
    def strip_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class UnitPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    active: Optional[bool] = None


class UnitOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    active: bool
    routes: int = 0


def _unit_out(db: Session, u: Unit) -> UnitOut:
    n = db.scalar(select(func.count()).select_from(Routing).where(Routing.unit_id == u.id)) or 0
    return UnitOut(id=u.id, type=u.type, name=u.name, active=u.active, routes=n)


@router.get("/units", response_model=list[UnitOut])
def list_units(type: Optional[str] = None, db: Session = Depends(get_db)):
    q = select(Unit).order_by(Unit.type, Unit.name)
    if type:
        q = q.where(Unit.type == type)
    return [_unit_out(db, u) for u in db.scalars(q).all()]


@router.post("/units", response_model=UnitOut, status_code=201)
def create_unit(body: UnitIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    if db.scalar(select(Unit.id).where(Unit.type == body.type, func.lower(Unit.name) == body.name.lower())):
        raise _conflict("This location already exists")
    u = Unit(type=body.type, name=body.name)
    db.add(u)
    db.flush()
    audit(db, admin, "create", "unit", u.id, f"{u.type}: {u.name}")
    db.commit()
    return _unit_out(db, u)


@router.patch("/units/{unit_id}", response_model=UnitOut)
def update_unit(unit_id: uuid.UUID, body: UnitPatch, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    u = db.get(Unit, unit_id)
    if u is None:
        raise ServiceError(404, "Not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if db.scalar(select(Unit.id).where(Unit.type == u.type, func.lower(Unit.name) == changes["name"].lower(),
                                           Unit.id != u.id)):
            raise _conflict("This location already exists")
    for k, v in changes.items():
        setattr(u, k, v)
    audit(db, admin, "update", "unit", u.id, f"{u.name}: {sorted(changes)}")
    db.commit()
    return _unit_out(db, u)


# =============================== routing ===============================

class RoutingIn(BaseModel):
    category_id: uuid.UUID
    unit_id: Optional[uuid.UUID] = None
    level0_user_id: uuid.UUID
    level1_user_id: Optional[uuid.UUID] = None
    level2_user_id: Optional[uuid.UUID] = None


class RoutingPatch(BaseModel):
    level0_user_id: Optional[uuid.UUID] = None
    level1_user_id: Optional[uuid.UUID] = None
    level2_user_id: Optional[uuid.UUID] = None


class PersonOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    active: bool


class IdName(BaseModel):
    id: uuid.UUID
    name: str


class RoutingOut(BaseModel):
    id: uuid.UUID
    category: IdName
    unit: Optional[IdName]
    level0: PersonOut
    level1: Optional[PersonOut]
    level2: Optional[PersonOut]


class RoutingPage(BaseModel):
    items: list[RoutingOut]
    total: int


def _person(u: Optional[User]) -> Optional[PersonOut]:
    return PersonOut(id=u.id, name=u.name, email=u.email, role=u.role, active=u.active) if u else None


def _routing_out(db: Session, r: Routing) -> RoutingOut:
    g = lambda uid: db.get(User, uid) if uid else None
    return RoutingOut(id=r.id, category=IdName(id=r.category.id, name=r.category.name),
                      unit=IdName(id=r.unit.id, name=r.unit.name) if r.unit else None,
                      level0=_person(g(r.level0_user_id)), level1=_person(g(r.level1_user_id)),
                      level2=_person(g(r.level2_user_id)))


def validate_route(db: Session, category: Category, unit: Optional[Unit], levels: list[Optional[uuid.UUID]]) -> list[str]:
    """Return a list of problems (empty = valid). Used by the API and by the CSV import."""
    errors = []
    if unit is not None and unit.type != category.unit_type:
        errors.append(f'Location "{unit.name}" is a {unit.type}, but this category uses {category.unit_type} locations')
    if levels[0] is None:
        errors.append("Level 0 (the first person) is required")
    if levels[2] is not None and levels[1] is None:
        errors.append("Level 2 needs a level 1")
    ids = [x for x in levels if x is not None]
    if len(set(ids)) != len(ids):
        errors.append("The same person cannot appear at two levels")
    for i, uid in enumerate(levels):
        if uid is None:
            continue
        u = db.get(User, uid)
        if u is None:
            errors.append(f"Level {i}: person not found")
        elif not u.active:
            errors.append(f"Level {i}: {u.email} is deactivated")
        elif u.role not in STAFF_ROLES:
            errors.append(f"Level {i}: {u.email} is a {u.role}; only staff or officers can handle tickets")
        elif category.confidential and u.role != Role.OFFICER:
            errors.append(f"Level {i}: {u.email} is not a designated officer, and this category is confidential")
    return errors


def _find_route(db: Session, category_id, unit_id) -> Optional[Routing]:
    return db.scalar(select(Routing).where(Routing.category_id == category_id,
                                           Routing.unit_id.is_(None) if unit_id is None else Routing.unit_id == unit_id))


@router.get("/routing", response_model=RoutingPage)
def list_routing(category_id: Optional[uuid.UUID] = None, limit: int = Query(100, ge=1, le=500),
                 offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    q = select(Routing).join(Category, Routing.category_id == Category.id)
    if category_id:
        q = q.where(Routing.category_id == category_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Category.name, Routing.unit_id.is_(None).desc()).limit(limit).offset(offset)).all()
    return RoutingPage(items=[_routing_out(db, r) for r in rows], total=total)


@router.post("/routing", response_model=RoutingOut, status_code=201)
def create_route(body: RoutingIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    cat = db.get(Category, body.category_id)
    if cat is None:
        raise ServiceError(422, "Unknown category")
    unit = db.get(Unit, body.unit_id) if body.unit_id else None
    if body.unit_id and unit is None:
        raise ServiceError(422, "Unknown location")
    problems = validate_route(db, cat, unit, [body.level0_user_id, body.level1_user_id, body.level2_user_id])
    if problems:
        raise ServiceError(422, "; ".join(problems), problems=problems)
    if _find_route(db, cat.id, unit.id if unit else None):
        raise _conflict("A route for this category and location already exists. Edit it instead.")
    r = Routing(category_id=cat.id, unit_id=unit.id if unit else None, level0_user_id=body.level0_user_id,
                level1_user_id=body.level1_user_id, level2_user_id=body.level2_user_id)
    db.add(r)
    db.flush()
    audit(db, admin, "create", "routing", r.id, f"{cat.name} / {unit.name if unit else 'default'}")
    db.commit()
    return _routing_out(db, r)


@router.patch("/routing/{route_id}", response_model=RoutingOut)
def update_route(route_id: uuid.UUID, body: RoutingPatch, admin: User = Depends(admin_only),
                 db: Session = Depends(get_db)):
    r = db.get(Routing, route_id)
    if r is None:
        raise ServiceError(404, "Not found")
    new = {"level0_user_id": r.level0_user_id, "level1_user_id": r.level1_user_id, "level2_user_id": r.level2_user_id}
    new.update(body.model_dump(exclude_unset=True))
    problems = validate_route(db, r.category, r.unit, [new["level0_user_id"], new["level1_user_id"], new["level2_user_id"]])
    if problems:
        raise ServiceError(422, "; ".join(problems), problems=problems)
    for k, v in new.items():
        setattr(r, k, v)
    audit(db, admin, "update", "routing", r.id, f"{r.category.name} / {r.unit.name if r.unit else 'default'}")
    db.commit()
    return _routing_out(db, r)


@router.delete("/routing/{route_id}", status_code=204)
def delete_route(route_id: uuid.UUID, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    r = db.get(Routing, route_id)
    if r is None:
        raise ServiceError(404, "Not found")
    if db.scalar(select(Ticket.id).where(Ticket.route_id == r.id).limit(1)):
        raise _conflict("Tickets already use this route. Change the people on it instead of deleting it.")
    if r.unit_id is None and (r.category.name == FALLBACK_CATEGORY or (
            r.category.confidential and r.category.active and not _has_confidential_route_without(db, r))):
        raise _conflict("This default route is required for routing (fallback or confidential tickets)")
    label = f"{r.category.name} / {r.unit.name if r.unit else 'default'}"
    db.delete(r)
    audit(db, admin, "delete", "routing", route_id, label)
    db.commit()


def _has_confidential_route_without(db: Session, route: Routing) -> bool:
    for c in db.scalars(select(Category).where(Category.confidential.is_(True), Category.active.is_(True))).all():
        if db.scalar(select(Routing.id).where(Routing.category_id == c.id, Routing.unit_id.is_(None), Routing.id != route.id)):
            return True
    return False


# ---------- CSV import ----------

class ImportRow(BaseModel):
    row: int
    action: str            # create | update | error
    message: str = ""


class ImportResult(BaseModel):
    dry_run: bool
    created: int
    updated: int
    errors: int
    rows: list[ImportRow]


ROUTING_TEMPLATE = ("category,unit,level0_email,level1_email,level2_email\n"
                    "Hostel and housing,Hostel A,{d0}@{dom},{d1}@{dom},{d2}@{dom}\n"
                    "Library,,librarian@{dom},registrar@{dom},\n")
USERS_TEMPLATE = ("name,email,role,department,hostel,room\n"
                  "Ravi Kumar,ravi@{dom},student,CSE,Hostel A,A-101\n"
                  "Meena Rao,meena@{dom},staff,,,\n")


@router.get("/routing/template", response_class=PlainTextResponse)
def routing_template():
    return PlainTextResponse(ROUTING_TEMPLATE.format(dom=get_settings().allowed_email_domain, d0="caretaker_a",
                                                     d1="warden", d2="chief_warden"), media_type="text/csv")


@router.post("/routing/import", response_model=ImportResult)
def import_routing(file: UploadFile = File(...), dry_run: bool = True, admin: User = Depends(admin_only),
                   db: Session = Depends(get_db)):
    """Preview with dry_run=true (default). Apply with dry_run=false: valid rows are saved, bad rows reported."""
    rows = read_csv(file, ["category", "unit", "level0_email", "level1_email", "level2_email"])
    results, created, updated = [], 0, 0
    for i, r in enumerate(rows, start=2):
        def fail(msg):
            results.append(ImportRow(row=i, action="error", message=msg))
        cat = db.scalar(select(Category).where(func.lower(Category.name) == r["category"].lower()))
        if cat is None:
            fail(f'Unknown category "{r["category"]}"'); continue
        unit = None
        if r["unit"]:
            unit = db.scalar(select(Unit).where(func.lower(Unit.name) == r["unit"].lower(), Unit.type == cat.unit_type,
                                                Unit.active.is_(True)))
            if unit is None:
                fail(f'Unknown {cat.unit_type} location "{r["unit"]}"'); continue
        levels, bad = [], False
        for col in ("level0_email", "level1_email", "level2_email"):
            email = r[col].lower()
            if not email:
                levels.append(None); continue
            u = db.scalar(select(User).where(User.email == email))
            if u is None:
                fail(f"No user with email {email}"); bad = True; break
            levels.append(u.id)
        if bad:
            continue
        problems = validate_route(db, cat, unit, levels)
        if problems:
            fail("; ".join(problems)); continue
        existing = _find_route(db, cat.id, unit.id if unit else None)
        if existing:
            existing.level0_user_id, existing.level1_user_id, existing.level2_user_id = levels
            updated += 1
            results.append(ImportRow(row=i, action="update"))
        else:
            db.add(Routing(category_id=cat.id, unit_id=unit.id if unit else None, level0_user_id=levels[0],
                           level1_user_id=levels[1], level2_user_id=levels[2]))
            created += 1
            results.append(ImportRow(row=i, action="create"))
        db.flush()
    errors = sum(1 for x in results if x.action == "error")
    if dry_run:
        db.rollback()
    else:
        audit(db, admin, "import", "routing", None, f"{created} created, {updated} updated, {errors} rejected")
        db.commit()
    return ImportResult(dry_run=dry_run, created=created, updated=updated, errors=errors, rows=results)


# =============================== users ===============================

class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=320)
    role: Literal["student", "staff", "officer", "admin"] = "student"
    department: Optional[str] = Field(default=None, max_length=100)
    hostel: Optional[str] = Field(default=None, max_length=100)
    room: Optional[str] = Field(default=None, max_length=50)


class UserPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    role: Optional[Literal["student", "staff", "officer", "admin"]] = None
    department: Optional[str] = Field(default=None, max_length=100)
    hostel: Optional[str] = Field(default=None, max_length=100)
    room: Optional[str] = Field(default=None, max_length=50)
    active: Optional[bool] = None


class UserOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    department: Optional[str]
    hostel: Optional[str]
    room: Optional[str]
    active: bool
    created_at: datetime
    in_routes: int = 0
    warnings: list[str] = []


class UserPage(BaseModel):
    items: list[UserOut]
    total: int


def _routes_for(db: Session, user_id) -> int:
    return db.scalar(select(func.count()).select_from(Routing).where(or_(
        Routing.level0_user_id == user_id, Routing.level1_user_id == user_id, Routing.level2_user_id == user_id))) or 0


def _user_out(db: Session, u: User, warnings=None) -> UserOut:
    return UserOut(id=u.id, name=u.name, email=u.email, role=u.role, department=u.department, hostel=u.hostel,
                   room=u.room, active=u.active, created_at=u.created_at, in_routes=_routes_for(db, u.id),
                   warnings=warnings or [])


def _check_email(email: str) -> str:
    email = email.strip().lower()
    domain = get_settings().allowed_email_domain.lower()
    if not EMAIL_RE.match(email) or not email.endswith("@" + domain):
        raise ServiceError(422, f"Email must be a valid @{domain} address")
    return email


def _active_admins_after(db: Session, user: User, new_role: str, new_active: bool) -> int:
    admins = db.scalars(select(User).where(User.role == Role.ADMIN, User.active.is_(True))).all()
    remaining = [a for a in admins if a.id != user.id]
    if new_role == Role.ADMIN and new_active:
        remaining.append(user)
    return len(remaining)


def _guard_user_change(db: Session, admin: User, u: User, role: str, active: bool) -> None:
    if u.id == admin.id and (role != u.role or active is False):
        raise _conflict("You cannot change your own role or deactivate yourself")
    if u.role == Role.ADMIN and (role != Role.ADMIN or not active) and _active_admins_after(db, u, role, active) < 1:
        raise _conflict("At least one active admin must remain")


@router.get("/users", response_model=UserPage)
def list_users(role: Optional[str] = None, active: Optional[bool] = None, q: Optional[str] = None,
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if active is not None:
        query = query.where(User.active.is_(active))
    if q:
        like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(func.lower(User.name).like(like, escape="\\"), func.lower(User.email).like(like, escape="\\")))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(User.name).limit(limit).offset(offset)).all()
    return UserPage(items=[_user_out(db, u) for u in rows], total=total)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    email = _check_email(body.email)
    if db.scalar(select(User.id).where(User.email == email)):
        raise _conflict("A user with this email already exists")
    u = User(name=body.name.strip(), email=email, role=body.role, department=body.department,
             hostel=body.hostel, room=body.room)
    db.add(u)
    db.flush()
    audit(db, admin, "create", "user", u.id, f"{u.email} as {u.role}")
    db.commit()
    return _user_out(db, u)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserPatch, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise ServiceError(404, "Not found")
    changes = body.model_dump(exclude_unset=True)
    new_role, new_active = changes.get("role", u.role), changes.get("active", u.active)
    _guard_user_change(db, admin, u, new_role, new_active)
    warnings = []
    n = _routes_for(db, u.id)
    if n and (new_active is False or new_role not in STAFF_ROLES) and (u.active or u.role in STAFF_ROLES):
        warnings.append(f"This person is in {n} routing row(s). Tickets skip deactivated people, but update those rows.")
    for k, v in changes.items():
        setattr(u, k, v)
    audit(db, admin, "update", "user", u.id, f"{u.email}: {sorted(changes)}")
    db.commit()
    return _user_out(db, u, warnings)


@router.get("/users/template", response_class=PlainTextResponse)
def users_template():
    return PlainTextResponse(USERS_TEMPLATE.format(dom=get_settings().allowed_email_domain), media_type="text/csv")


@router.post("/users/import", response_model=ImportResult)
def import_users(file: UploadFile = File(...), dry_run: bool = True, admin: User = Depends(admin_only),
                 db: Session = Depends(get_db)):
    """Add or update users by email. Existing users keep their active flag. Preview first (dry_run=true)."""
    rows = read_csv(file, ["name", "email"])
    results, created, updated = [], 0, 0
    for i, r in enumerate(rows, start=2):
        try:
            email = _check_email(r["email"])
            role = (r.get("role") or "student").lower()
            if role not in Role.ALL:
                raise ServiceError(422, f'Unknown role "{role}"')
            if not r["name"]:
                raise ServiceError(422, "Name is required")
            u = db.scalar(select(User).where(User.email == email))
            if u is None:
                db.add(User(name=r["name"], email=email, role=role, department=r.get("department") or None,
                            hostel=r.get("hostel") or None, room=r.get("room") or None))
                created += 1
                results.append(ImportRow(row=i, action="create"))
            else:
                _guard_user_change(db, admin, u, role, u.active)
                u.name, u.role = r["name"], role
                u.department, u.hostel, u.room = r.get("department") or None, r.get("hostel") or None, r.get("room") or None
                updated += 1
                results.append(ImportRow(row=i, action="update"))
            db.flush()
        except ServiceError as e:
            results.append(ImportRow(row=i, action="error", message=e.detail))
    errors = sum(1 for x in results if x.action == "error")
    if dry_run:
        db.rollback()
    else:
        audit(db, admin, "import", "user", None, f"{created} created, {updated} updated, {errors} rejected")
        db.commit()
    return ImportResult(dry_run=dry_run, created=created, updated=updated, errors=errors, rows=results)


# =============================== audit log ===============================

class AuditOut(BaseModel):
    at: datetime
    actor: str
    action: str
    entity: str
    entity_id: Optional[str]
    detail: Optional[str]


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int


@router.get("/audit", response_model=AuditPage)
def list_audit(entity: Optional[str] = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db)):
    q = select(AuditLog)
    if entity:
        q = q.where(AuditLog.entity == entity)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()
    out = []
    for a in rows:
        actor = db.get(User, a.actor_id) if a.actor_id else None
        out.append(AuditOut(at=a.created_at, actor=actor.email if actor else "system", action=a.action,
                            entity=a.entity, entity_id=a.entity_id, detail=a.detail))
    return AuditPage(items=out, total=total)
