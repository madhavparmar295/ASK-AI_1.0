"""Seed data for development and tests. Safe to run more than once.

    python -m grievance_app.seed

Creates the example categories, units, staff, students and routing rows.
Replace with the admin block's real data through the admin pages (Stage 3/5).
"""
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .constants import Role, UnitType
from .models import Category, Routing, Unit, User
from .services.keywords import DEFAULT_KEYWORDS

# key, name, role, department, hostel, room
USERS = [
    ("admin", "Admin Office", Role.ADMIN, None, None, None),
    ("cell", "Grievance Cell", Role.STAFF, None, None, None),
    ("officer1", "Designated Officer 1", Role.OFFICER, None, None, None),
    ("officer2", "Designated Officer 2", Role.OFFICER, None, None, None),
    ("caretaker_a", "Caretaker Hostel A", Role.STAFF, None, None, None),
    ("caretaker_b", "Caretaker Hostel B", Role.STAFF, None, None, None),
    ("warden", "Warden", Role.STAFF, None, None, None),
    ("chief_warden", "Chief Warden", Role.STAFF, None, None, None),
    ("maintenance", "Maintenance Supervisor", Role.STAFF, None, None, None),
    ("estate_officer", "Estate Officer", Role.STAFF, None, None, None),
    ("it_helpdesk", "IT Helpdesk", Role.STAFF, None, None, None),
    ("it_head", "IT Head", Role.STAFF, None, None, None),
    ("coordinator_cse", "CSE Coordinator", Role.STAFF, "CSE", None, None),
    ("hod_cse", "CSE HOD", Role.STAFF, "CSE", None, None),
    ("coordinator_ece", "ECE Coordinator", Role.STAFF, "ECE", None, None),
    ("hod_ece", "ECE HOD", Role.STAFF, "ECE", None, None),
    ("dean", "Dean Academics", Role.STAFF, None, None, None),
    ("exam_clerk", "Exam Cell Clerk", Role.STAFF, None, None, None),
    ("controller", "Controller of Examinations", Role.STAFF, None, None, None),
    ("accounts_clerk", "Accounts Clerk", Role.STAFF, None, None, None),
    ("accounts_officer", "Accounts Officer", Role.STAFF, None, None, None),
    ("registrar", "Registrar", Role.STAFF, None, None, None),
    ("admin_office", "Admin Office Clerk", Role.STAFF, None, None, None),
    ("librarian", "Librarian", Role.STAFF, None, None, None),
    ("transport", "Transport In-charge", Role.STAFF, None, None, None),
    ("mess_manager", "Mess Manager", Role.STAFF, None, None, None),
    ("ravi", "Ravi Kumar", Role.STUDENT, "CSE", "Hostel A", "A-101"),
    ("priya", "Priya Sharma", Role.STUDENT, "ECE", "Hostel B", "B-205"),
    ("aman", "Aman Verma", Role.STUDENT, "CSE", "Hostel A", "A-110"),
]

# name, confidential, sla_hours, unit_type
CATEGORIES = [
    ("Hostel and housing", False, 24, UnitType.HOSTEL),
    ("Campus infrastructure", False, 48, UnitType.BUILDING),
    ("IT and network", False, 24, UnitType.CAMPUS),
    ("Academics", False, 120, UnitType.DEPARTMENT),
    ("Examinations", False, 72, UnitType.CAMPUS),
    ("Fees and accounts", False, 72, UnitType.CAMPUS),
    ("Scholarships and documents", False, 120, UnitType.CAMPUS),
    ("Library", False, 72, UnitType.CAMPUS),
    ("Transport", False, 72, UnitType.CAMPUS),
    ("Mess and canteen", False, 48, UnitType.MESS),
    ("Harassment, ragging, discrimination, safety", True, 24, UnitType.CAMPUS),
    ("Other", False, 72, UnitType.CAMPUS),
]

# type, name
UNITS = [
    (UnitType.HOSTEL, "Hostel A"), (UnitType.HOSTEL, "Hostel B"),
    (UnitType.DEPARTMENT, "CSE"), (UnitType.DEPARTMENT, "ECE"),
    (UnitType.BUILDING, "Main Block"), (UnitType.BUILDING, "Library Block"),
    (UnitType.MESS, "Main Mess"), (UnitType.CAMPUS, "Campus"),
]

# category, unit name or None (= category default), level0, level1, level2 (user keys)
ROUTES = [
    ("Hostel and housing", "Hostel A", "caretaker_a", "warden", "chief_warden"),
    ("Hostel and housing", "Hostel B", "caretaker_b", "warden", "chief_warden"),
    ("Hostel and housing", None, "warden", "chief_warden", None),
    ("Campus infrastructure", None, "maintenance", "estate_officer", "registrar"),
    ("IT and network", None, "it_helpdesk", "it_head", "registrar"),
    ("Academics", "CSE", "coordinator_cse", "hod_cse", "dean"),
    ("Academics", "ECE", "coordinator_ece", "hod_ece", "dean"),
    ("Academics", None, "cell", "dean", None),
    ("Examinations", None, "exam_clerk", "controller", "dean"),
    ("Fees and accounts", None, "accounts_clerk", "accounts_officer", "registrar"),
    ("Scholarships and documents", None, "admin_office", "registrar", None),
    ("Library", None, "librarian", "registrar", None),
    ("Transport", None, "transport", "registrar", None),
    ("Mess and canteen", None, "mess_manager", "warden", "chief_warden"),
    ("Harassment, ragging, discrimination, safety", None, "officer1", "officer2", None),
    ("Other", None, "cell", "registrar", None),
]


def seed(db: Session) -> dict:
    # In the combined deployment the host sets ENVIRONMENT for the chatbot and the
    # grievance side may not set GRIEVANCE_ENV at all. Either one saying "production"
    # is enough to refuse: demo users on a real server would be a serious mistake.
    production = get_settings().is_production or os.getenv("ENVIRONMENT", "").lower() == "production"
    if production:
        raise RuntimeError("seed creates fake test users and must never run in production. "
                           "Use 'python -m grievance_app.init_data' and 'python -m grievance_app.create_admin' instead.")
    domain = get_settings().allowed_email_domain
    users = {}
    for key, name, role, dept, hostel, room in USERS:
        email = f"{key}@{domain}"
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(name=name, email=email, role=role, department=dept, hostel=hostel, room=room)
            db.add(u)
        users[key] = u

    cats = {}
    for name, conf, hours, unit_type in CATEGORIES:
        c = db.scalar(select(Category).where(Category.name == name))
        if c is None:
            c = Category(name=name, confidential=conf, sla_hours=hours, unit_type=unit_type)
            db.add(c)
        if not c.keywords and name in DEFAULT_KEYWORDS:
            c.keywords = DEFAULT_KEYWORDS[name]
        cats[name] = c

    units = {}
    for utype, name in UNITS:
        un = db.scalar(select(Unit).where(Unit.type == utype, Unit.name == name))
        if un is None:
            un = Unit(type=utype, name=name)
            db.add(un)
        units[name] = un
    db.flush()  # assigns ids

    for cat, unit, l0, l1, l2 in ROUTES:
        unit_id = units[unit].id if unit else None
        exists_ = db.scalar(select(Routing).where(
            Routing.category_id == cats[cat].id,
            Routing.unit_id.is_(None) if unit_id is None else Routing.unit_id == unit_id))
        if exists_ is None:
            db.add(Routing(category_id=cats[cat].id, unit_id=unit_id,
                           level0_user_id=users[l0].id,
                           level1_user_id=users[l1].id if l1 else None,
                           level2_user_id=users[l2].id if l2 else None))
    db.commit()
    return {"users": users, "categories": cats, "units": units}


if __name__ == "__main__":
    from .db import SessionLocal
    with SessionLocal() as session:
        result = seed(session)
    print(f"Seeded {len(result['users'])} users, {len(result['categories'])} categories, "
          f"{len(result['units'])} units, {len(ROUTES)} routing rows.")
