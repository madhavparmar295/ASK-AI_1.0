import itertools

import pytest
from fastapi import Depends, HTTPException
from sqlalchemy import select

from grievance_app.constants import Role
from grievance_app.models import Event, Routing, Ticket, User
from grievance_app.permissions import (can_download_attachment, can_escalate, can_handle,
                             can_view, get_ticket_or_404, ticket_visibility_filter,
                             visible_events)
from grievance_app.security.deps import require_role
from tests.grievance.conftest import login_as

_counter = itertools.count(1)


def make_ticket(db, world, reporter, category, unit, assignee, confidential=False, with_route=True):
    cat = world["categories"][category]
    unit_obj = world["units"][unit] if unit else None
    route = db.scalar(select(Routing).where(
        Routing.category_id == cat.id,
        Routing.unit_id.is_(None) if unit_obj is None else Routing.unit_id == unit_obj.id))
    t = Ticket(ticket_no=f"T-{next(_counter)}", reporter_id=world["users"][reporter].id,
               category_id=cat.id, unit_id=unit_obj.id if unit_obj else None,
               route_id=route.id if (with_route and route) else None,
               description="test", assignee_id=world["users"][assignee].id,
               confidential=confidential)
    db.add(t)
    db.commit()
    return t


@pytest.fixture()
def tickets(db_session, world):
    return {
        # normal hostel ticket: chain = caretaker_a -> warden -> chief_warden
        "hostel": make_ticket(db_session, world, "ravi", "Hostel and housing", "Hostel A", "caretaker_a"),
        # confidential: chain = officer1 -> officer2
        "conf": make_ticket(db_session, world, "priya", "Harassment, ragging, discrimination, safety",
                            None, "officer1", confidential=True),
        # reported by a staff member against their own queue (conflict of interest)
        "own": make_ticket(db_session, world, "caretaker_a", "Hostel and housing", "Hostel A", "caretaker_a"),
        # no route stored, assigned to the grievance cell
        "unrouted": make_ticket(db_session, world, "aman", "Other", None, "cell", with_route=False),
    }


def u(world, key):
    return world["users"][key]


# ---------- can_view: the matrix from the design ----------

VIEW_NORMAL = {
    "ravi": True, "priya": False, "aman": False,          # reporter / other students
    "caretaker_a": True, "caretaker_b": False,            # assignee / other hostel's caretaker
    "warden": True, "chief_warden": True,                 # heads in the chain
    "admin": True, "cell": False, "officer1": False, "hod_cse": False,
}
VIEW_CONF = {
    "priya": True, "ravi": False,
    "officer1": True, "officer2": True,                   # officers in the chain
    "admin": False, "warden": False, "cell": False, "caretaker_a": False, "registrar": False,
}


@pytest.mark.parametrize("key,expected", VIEW_NORMAL.items())
def test_view_normal_ticket(world, tickets, key, expected):
    assert can_view(u(world, key), tickets["hostel"]) is expected


@pytest.mark.parametrize("key,expected", VIEW_CONF.items())
def test_view_confidential_ticket(world, tickets, key, expected):
    assert can_view(u(world, key), tickets["conf"]) is expected


def test_non_officer_in_chain_cannot_view_confidential(db_session, world, tickets):
    """Even someone placed in the confidential route cannot see it unless they are an officer."""
    route = db_session.get(Routing, tickets["conf"].route_id)
    route.level2_user_id = u(world, "registrar").id
    db_session.commit()
    db_session.refresh(tickets["conf"])
    assert can_view(u(world, "registrar"), tickets["conf"]) is False
    assert can_handle(u(world, "registrar"), tickets["conf"]) is False


def test_unrouted_ticket_visible_to_assignee_only(world, tickets):
    t = tickets["unrouted"]
    assert can_view(u(world, "cell"), t) and can_view(u(world, "aman"), t)
    assert not can_view(u(world, "ravi"), t)
    assert can_view(u(world, "admin"), t)


def test_download_follows_view(world, tickets):
    assert can_download_attachment(u(world, "ravi"), tickets["hostel"])
    assert not can_download_attachment(u(world, "priya"), tickets["hostel"])
    assert not can_download_attachment(u(world, "admin"), tickets["conf"])


# ---------- handle / escalate ----------

@pytest.mark.parametrize("key,handle,escalate", [
    ("caretaker_a", True, False),     # assignee can work it, cannot escalate by hand
    ("warden", True, True),           # head
    ("chief_warden", True, True),
    ("admin", False, True),           # admin can escalate normal tickets, not resolve
    ("ravi", False, False),           # reporter
    ("caretaker_b", False, False),
    ("cell", False, False),
])
def test_handle_and_escalate_normal(world, tickets, key, handle, escalate):
    t = tickets["hostel"]
    assert can_handle(u(world, key), t) is handle
    assert can_escalate(u(world, key), t) is escalate


@pytest.mark.parametrize("key,handle,escalate", [
    ("officer1", True, True), ("officer2", True, True),
    ("admin", False, False), ("warden", False, False), ("priya", False, False),
])
def test_handle_and_escalate_confidential(world, tickets, key, handle, escalate):
    t = tickets["conf"]
    assert can_handle(u(world, key), t) is handle
    assert can_escalate(u(world, key), t) is escalate


def test_reporter_cannot_handle_own_ticket(world, tickets):
    t = tickets["own"]                       # caretaker_a reported it and is also assignee
    assert can_view(u(world, "caretaker_a"), t) is True
    assert can_handle(u(world, "caretaker_a"), t) is False
    assert can_escalate(u(world, "caretaker_a"), t) is False
    assert can_handle(u(world, "warden"), t) is True


# ---------- SQL filter equals can_view for every user and ticket ----------

def test_sql_filter_matches_python_check(db_session, world, tickets):
    all_tickets = db_session.scalars(select(Ticket)).all()
    for key, user in world["users"].items():
        visible_sql = {t.id for t in db_session.scalars(
            select(Ticket).where(ticket_visibility_filter(user))).all()}
        visible_py = {t.id for t in all_tickets if can_view(user, t)}
        assert visible_sql == visible_py, key


# ---------- 404 behaviour ----------

def test_get_ticket_or_404(db_session, world, tickets):
    assert get_ticket_or_404(db_session, u(world, "ravi"), tickets["hostel"].id).id == tickets["hostel"].id
    with pytest.raises(HTTPException) as e:
        get_ticket_or_404(db_session, u(world, "priya"), tickets["hostel"].id)
    assert e.value.status_code == 404
    import uuid
    with pytest.raises(HTTPException) as e2:       # unknown id looks identical
        get_ticket_or_404(db_session, u(world, "priya"), uuid.uuid4())
    assert e2.value.status_code == 404 and e2.value.detail == e.value.detail


# ---------- events ----------

def test_reporter_sees_only_student_visible_events(db_session, world, tickets):
    t = tickets["hostel"]
    events = [Event(ticket_id=t.id, type="status", text="Assigned", visible_to_student=True),
              Event(ticket_id=t.id, type="note", text="internal note", visible_to_student=False)]
    assert [e.text for e in visible_events(u(world, "ravi"), t, events)] == ["Assigned"]
    assert len(visible_events(u(world, "warden"), t, events)) == 2


# ---------- role dependency ----------

def test_require_role_returns_404_for_wrong_role(client):
    @client.app.get("/api/grievance/_test/admin-only")
    def admin_only(user: User = Depends(require_role(Role.ADMIN))):
        return {"ok": True, "email": user.email}

    assert client.get("/api/grievance/_test/admin-only").status_code == 401   # not logged in
    login_as(client, "ravi")
    assert client.get("/api/grievance/_test/admin-only").status_code == 404   # student
    login_as(client, "warden")
    assert client.get("/api/grievance/_test/admin-only").status_code == 404   # staff
    login_as(client, "admin")
    assert client.get("/api/grievance/_test/admin-only").status_code == 200
