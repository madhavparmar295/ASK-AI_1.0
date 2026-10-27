from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from grievance_app.create_admin import create_admin
from grievance_app.models import Attachment, AuditLog, Event, Feedback, Notification, Ticket, User
from grievance_app.retention import purge
from tests.grievance.conftest import login_as, logout, new_issue

CONF = "Harassment, ragging, discrimination, safety"
API = "/api/grievance"


# ---------- create_admin ----------

def test_creates_a_new_admin(db_session, world):
    user, result = create_admin(db_session, " Head.IT@College.edu ", "IT Head")
    assert result == "created" and user.role == "admin" and user.email == "head.it@college.edu" and user.active
    assert db_session.scalars(select(AuditLog)).one().action == "created"


def test_promotes_and_reactivates_an_existing_user(db_session, world):
    ravi = world["users"]["ravi"]
    ravi.active = False
    db_session.commit()
    user, result = create_admin(db_session, "ravi@college.edu", "")
    assert result == "promoted" and user.role == "admin" and user.active is True


@pytest.mark.parametrize("email,name", [("someone@gmail.com", "X"), ("x@evilcollege.edu", "X"), ("not-an-email", "X"), ("new@college.edu", " ")])
def test_refuses_bad_input(db_session, world, email, name):
    with pytest.raises(ValueError):
        create_admin(db_session, email, name)


def test_the_new_admin_can_use_the_admin_pages(client, db_session, world):
    create_admin(db_session, "newadmin@college.edu", "New Admin")
    r = client.post(f"{API}/auth/dev-login", json={"email": "newadmin@college.edu"})
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert client.get(f"{API}/admin/stats").status_code == 200


# ---------- retention ----------

def _old(db, ticket, years, status="CLOSED"):
    when = datetime.now(timezone.utc) - timedelta(days=365 * years + 5)
    ticket.status, ticket.closed_at, ticket.updated_at = status, when, when
    db.commit()


@pytest.fixture()
def tickets(client, world, db_session, settings, tmp_path):
    settings.upload_dir = str(tmp_path / "up")
    out = {}
    logout(client); login_as(client, "ravi")
    out["old"] = db_session.get(Ticket, __import__("uuid").UUID(new_issue(client, world).json()["id"]))
    out["recent"] = db_session.get(Ticket, __import__("uuid").UUID(new_issue(client, world, category="Library", unit=None).json()["id"]))
    out["open"] = db_session.get(Ticket, __import__("uuid").UUID(new_issue(client, world, category="Transport", unit=None).json()["id"]))
    logout(client); login_as(client, "priya")
    out["conf"] = db_session.get(Ticket, __import__("uuid").UUID(new_issue(client, world, category=CONF, unit=None).json()["id"]))
    _old(db_session, out["old"], 4)
    _old(db_session, out["recent"], 1)
    _old(db_session, out["conf"], 10)
    return out


def test_does_nothing_when_switched_off(db_session, tickets):
    assert purge(db_session, apply=True)["tickets"] == 0
    assert db_session.scalar(select(Ticket).where(Ticket.id == tickets["old"].id)) is not None


def test_dry_run_changes_nothing(db_session, tickets, settings):
    settings.retention_years = 3
    r = purge(db_session)
    assert r == {**r, "applied": False, "tickets": 1, "confidential": 0}
    assert db_session.get(Ticket, tickets["old"].id) is not None


def test_deletes_only_old_finished_normal_tickets(db_session, tickets, settings):
    settings.retention_years = 3
    r = purge(db_session, apply=True)
    assert r["tickets"] == 1
    assert db_session.get(Ticket, tickets["old"].id) is None
    for keep in ("recent", "open", "conf"):                      # too new / still open / confidential not enabled
        assert db_session.get(Ticket, tickets[keep].id) is not None


def test_confidential_has_its_own_period(db_session, tickets, settings):
    settings.retention_confidential_years = 7
    assert purge(db_session, apply=True)["tickets"] == 1
    assert db_session.get(Ticket, tickets["conf"].id) is None
    assert db_session.get(Ticket, tickets["old"].id) is not None


def test_open_tickets_are_never_deleted_however_old(db_session, tickets, settings):
    settings.retention_years = 1
    t = tickets["open"]
    t.created_at = t.updated_at = datetime.now(timezone.utc) - timedelta(days=365 * 20)
    db_session.commit()
    purge(db_session, apply=True)
    assert db_session.get(Ticket, t.id) is not None


def test_removes_everything_belonging_to_the_ticket_including_files(db_session, tickets, settings, client, upload_dir=None):
    import os
    settings.retention_years = 3
    t = tickets["old"]
    folder = __import__("pathlib").Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "secret.png").write_bytes(b"\x89PNG")
    db_session.add(Attachment(ticket_id=t.id, uploaded_by=t.reporter_id, stored_name="secret.png", original_name="a.png",
                              mime_type="image/png", size_bytes=4))
    db_session.add(Feedback(ticket_id=t.id, rating=5))
    db_session.commit()
    n_events = len(db_session.scalars(select(Event).where(Event.ticket_id == t.id)).all())
    assert n_events > 0
    r = purge(db_session, apply=True)
    assert r["files"] == 1 and not (folder / "secret.png").exists()
    for model in (Event, Attachment, Feedback, Notification):
        assert db_session.scalars(select(model).where(model.ticket_id == t.id)).all() == []
    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == "purge")).one()
    assert "1 tickets" in entry.detail and "secret" not in entry.detail            # the log says how many, never what


def test_a_missing_file_does_not_stop_the_purge(db_session, tickets, settings):
    settings.retention_years = 3
    t = tickets["old"]
    db_session.add(Attachment(ticket_id=t.id, uploaded_by=t.reporter_id, stored_name="gone.png", original_name="a.png",
                              mime_type="image/png", size_bytes=4))
    db_session.commit()
    assert purge(db_session, apply=True)["tickets"] == 1


def test_audit_log_survives(db_session, tickets, settings):
    settings.retention_years = 3
    before = len(db_session.scalars(select(AuditLog)).all())
    purge(db_session, apply=True)
    assert len(db_session.scalars(select(AuditLog)).all()) == before + 1


# ---------- first-time setup of a real installation ----------

def test_init_data_creates_only_categories_and_is_repeatable(db_session):
    from grievance_app.init_data import init_categories
    from grievance_app.models import Category, Routing, Unit
    assert init_categories(db_session) == 12
    assert init_categories(db_session) == 0
    assert db_session.scalar(select(__import__("sqlalchemy").func.count()).select_from(User)) == 0
    assert db_session.scalar(select(__import__("sqlalchemy").func.count()).select_from(Unit)) == 0
    assert db_session.scalar(select(__import__("sqlalchemy").func.count()).select_from(Routing)) == 0
    cats = {c.name: c for c in db_session.scalars(select(Category)).all()}
    assert cats["Other"].keywords and cats["Hostel and housing"].keywords
    assert [n for n, c in cats.items() if c.confidential] == ["Harassment, ragging, discrimination, safety"]


def test_init_data_leaves_existing_categories_alone(db_session):
    from grievance_app.init_data import init_categories
    from grievance_app.models import Category
    db_session.add(Category(name="Library", sla_hours=999, keywords="custom"))
    db_session.commit()
    assert init_categories(db_session) == 11
    lib = db_session.scalar(select(Category).where(Category.name == "Library"))
    assert (lib.sla_hours, lib.keywords) == (999, "custom")


def test_seed_refuses_to_run_in_production(db_session, settings):
    from grievance_app.seed import seed
    settings.env = "production"
    with pytest.raises(RuntimeError, match="never run in production"):
        seed(db_session)
    assert db_session.scalars(select(User)).all() == []


def test_a_fresh_installation_works_after_setup_and_routing(db_session, settings):
    """init_data + create_admin + the admin adding people and routing = a working system, no seed needed."""
    from fastapi.testclient import TestClient
    from grievance_app.db import get_db
    from grievance_app.init_data import init_categories
    from grievance_app.main import create_app
    from grievance_app.models import Category
    from grievance_app.security import ratelimit
    ratelimit.reset()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    client = TestClient(app)
    init_categories(db_session)
    create_admin(db_session, "boss@college.edu", "Boss")
    r = client.post(f"{API}/auth/dev-login", json={"email": "boss@college.edu"})
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    other = db_session.scalar(select(Category).where(Category.name == "Other"))
    conf = db_session.scalar(select(Category).where(Category.confidential.is_(True)))
    clerk = client.post(f"{API}/admin/users", json={"name": "Clerk", "email": "clerk@college.edu", "role": "staff"}).json()["id"]
    off = client.post(f"{API}/admin/users", json={"name": "Officer", "email": "officer@college.edu", "role": "officer"}).json()["id"]
    stu = client.post(f"{API}/admin/users", json={"name": "Stu", "email": "stu@college.edu", "role": "student"}).json()["id"]
    assert client.post(f"{API}/admin/routing", json={"category_id": str(other.id), "level0_user_id": clerk}).status_code == 201
    assert client.post(f"{API}/admin/routing", json={"category_id": str(conf.id), "level0_user_id": off}).status_code == 201
    client.post(f"{API}/auth/logout"); client.cookies.clear(); client.headers.pop("X-CSRF-Token")
    r = client.post(f"{API}/auth/dev-login", json={"email": "stu@college.edu"})
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    t = client.post(f"{API}/issues", json={"description": "Something is wrong near the gate", "category_id": str(other.id)})
    assert t.status_code == 201 and t.json()["assignee"]["name"] == "Clerk"
    lib = db_session.scalar(select(Category).where(Category.name == "Library"))        # no row of its own: falls back to Other
    t2 = client.post(f"{API}/issues", json={"description": "Library door is stuck", "category_id": str(lib.id)})
    assert t2.status_code == 201 and t2.json()["assignee"]["name"] == "Clerk"
