"""Create the first admin (or promote an existing user). Needed once, because in production
the sign-in is Google only and the admin pages need an admin to exist already.

    python -m grievance_app.create_admin --email head.it@college.edu --name "IT Head"
"""
import argparse
import re
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .constants import Role
from .models import User
from .services.audit import audit

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")


def create_admin(db: Session, email: str, name: str) -> tuple[User, str]:
    email = email.strip().lower()
    domain = get_settings().allowed_email_domain.lower()
    if not EMAIL_RE.match(email) or not email.endswith("@" + domain):
        raise ValueError(f"The email must be a valid @{domain} address")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        if not name.strip():
            raise ValueError("--name is required for a new user")
        user = User(name=name.strip(), email=email, role=Role.ADMIN)
        db.add(user)
        result = "created"
    else:
        user.role, user.active = Role.ADMIN, True
        result = "promoted"
    db.flush()
    audit(db, None, result, "user", user.id, f"{email} is now an admin (command line)")
    db.commit()
    return user, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="")
    args = parser.parse_args()
    from .db import SessionLocal
    try:
        with SessionLocal() as db:
            user, result = create_admin(db, args.email, args.name)
    except ValueError as e:
        sys.exit(f"Error: {e}")
    print(f"{user.email} {result} as admin.")


if __name__ == "__main__":
    main()
