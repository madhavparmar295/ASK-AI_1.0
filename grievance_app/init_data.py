"""Create the default categories (with their classifier keywords) on a NEW installation.

    python -m grievance_app.init_data

Safe to run more than once; it never changes a category that already exists. It creates NO users, NO locations
and NO routing: the admin adds those in the admin pages. (Do not use `app.seed` in production: it creates test users.)
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category
from .seed import CATEGORIES
from .services.audit import audit
from .services.keywords import DEFAULT_KEYWORDS


def init_categories(db: Session) -> int:
    created = 0
    for name, confidential, hours, unit_type in CATEGORIES:
        if db.scalar(select(Category.id).where(Category.name == name)) is None:
            db.add(Category(name=name, confidential=confidential, sla_hours=hours, unit_type=unit_type,
                            keywords=DEFAULT_KEYWORDS.get(name)))
            created += 1
    if created:
        audit(db, None, "create", "category", None, f"{created} default categories (initial setup)")
    db.commit()
    return created


def main() -> None:
    from .db import SessionLocal
    with SessionLocal() as db:
        n = init_categories(db)
    print(f"{n} categories created." if n else "All default categories already exist. Nothing to do.")


if __name__ == "__main__":
    main()
