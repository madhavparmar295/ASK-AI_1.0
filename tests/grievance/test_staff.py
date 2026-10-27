import uuid
from datetime import datetime, timedelta, timezone

from grievance_app.models import Ticket
from tests.grievance.conftest import login_as, logout, new_issue

API = "/api/grievance"


def make(client, world, who, **kw):
    logout(client); login_as(client, who)
    r = new_issue(client, world, **kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_only_staff_and_officers_reach_staff_endpoints(client, world):
    for who, code in (("ravi", 404), ("admin", 404), ("caretaker_a", 200), ("officer1", 200), ("warden", 200)):
        logout(client); login_as(client, who)
        assert client.get(f"{API}/staff/issues").status_code == code, who
        assert client.get(f"{API}/staff/overdue").status_code == code, who
    logout(client)
    assert client.get(f"{API}/staff/issues").status_code == 401


def test_my_queue_shows_assigned_tickets_with_reporter(client, world):
    a = make(client, world, "ravi")
    make(client, world, "priya", unit="Hostel B")
    logout(client); login_as(client, "caretaker_a")
    page = client.get(f"{API}/staff/issues").json()
    assert page["total"] == 1 and page["items"][0]["id"] == a
    assert page["items"][0]["reporter_name"] == "Ravi Kumar"


def test_team_scope_for_heads(client, world):
    make(client, world, "ravi")
    make(client, world, "priya", unit="Hostel B")
    logout(client); login_as(client, "warden")
    assert client.get(f"{API}/staff/issues").json()["total"] == 0                # nothing assigned to me
    assert client.get(f"{API}/staff/issues?scope=team").json()["total"] == 2     # both hostels are in my chain
    logout(client); login_as(client, "chief_warden")
    assert client.get(f"{API}/staff/issues?scope=team").json()["total"] == 2


def test_status_filter_and_sort_by_due_date(client, world, db_session):
    a = make(client, world, "ravi", category="Hostel and housing", unit=None)   # hostel default -> warden
    b = make(client, world, "ravi", category="Mess and canteen", unit=None)      # mess default -> mess manager
    logout(client); login_as(client, "warden")
    ids = [t["id"] for t in client.get(f"{API}/staff/issues?scope=team").json()["items"]]
    assert ids == [a, b]                 # soonest deadline first (hostel 24 h before mess 48 h)
    assert client.get(f"{API}/staff/issues?status=CLOSED").json()["total"] == 0
    assert client.get(f"{API}/staff/issues?status=BOGUS").status_code == 422


def test_overdue_list(client, world, db_session):
    a = make(client, world, "ravi")
    t = db_session.get(Ticket, uuid.UUID(a))
    t.due_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.commit()
    logout(client); login_as(client, "caretaker_a")
    item = client.get(f"{API}/staff/overdue").json()["items"][0]
    assert item["id"] == a and item["overdue"] is True
    logout(client); login_as(client, "warden")
    assert client.get(f"{API}/staff/overdue").json()["total"] == 1               # head sees it too
    logout(client); login_as(client, "caretaker_b")
    assert client.get(f"{API}/staff/overdue").json()["total"] == 0


def test_resolved_ticket_is_not_overdue(client, world, db_session):
    a = make(client, world, "ravi")
    t = db_session.get(Ticket, uuid.UUID(a))
    t.due_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.commit()
    logout(client); login_as(client, "caretaker_a")
    client.post(f"{API}/issues/{a}/resolve", json={"note": "done"})
    assert client.get(f"{API}/staff/overdue").json()["total"] == 0


def test_confidential_queue_is_for_officers_only(client, world):
    make(client, world, "priya", category="Harassment, ragging, discrimination, safety", unit=None)
    for who, expected in (("officer1", 1), ("officer2", 0), ("warden", 0), ("cell", 0)):
        logout(client); login_as(client, who)
        assert client.get(f"{API}/staff/issues?scope=team").json()["total"] == (1 if who in ("officer1", "officer2") else 0), who
    logout(client); login_as(client, "officer2")
    assert client.get(f"{API}/staff/issues?scope=team").json()["items"][0]["confidential"] is True


def test_own_tickets_do_not_appear_in_staff_queue(client, world):
    make(client, world, "caretaker_a")                   # a caretaker's own report
    assert client.get(f"{API}/staff/issues").json()["total"] == 0
    logout(client); login_as(client, "warden")
    assert client.get(f"{API}/staff/issues?scope=team").json()["total"] == 1


def test_pagination(client, world):
    for who_cat in ("Library", "Transport", "Fees and accounts"):   # registrar is in all three chains
        make(client, world, "ravi", category=who_cat, unit=None)
    logout(client); login_as(client, "registrar")
    page = client.get(f"{API}/staff/issues?scope=team&limit=2").json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["limit"] == 2
