from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from grievance_app.models import Event, Routing, Ticket
from grievance_app.services import tickets as svc
from tests.grievance.conftest import login_as, logout, new_issue

API = "/api/grievance"


def issue_id(r):
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------- creating and routing ----------

def test_create_routes_to_caretaker_with_deadline(client, world, db_session):
    login_as(client, "ravi")
    r = new_issue(client, world)
    assert r.status_code == 201
    d = r.json()
    assert d["status"] == "ASSIGNED" and d["ticket_no"].startswith("GRV-")
    assert d["assignee"]["name"] == "Caretaker Hostel A" and d["escalation_level"] == 0
    assert d["reporter"] is None                                   # reporters don't see themselves
    due = svc.aware(datetime.fromisoformat(d["due_at"]))
    assert abs((due - datetime.now(timezone.utc)) - timedelta(hours=24)) < timedelta(minutes=2)
    assert "cancel" in d["actions"] and "reply" in d["actions"]
    assert [e["text"] for e in d["events"]] == ["Ticket created"]


def test_client_cannot_set_status_or_assignee(client, world, db_session):
    login_as(client, "ravi")
    r = new_issue(client, world, status="RESOLVED", assignee_id=str(world["users"]["admin"].id),
                  urgent=True, escalation_level=2)
    d = r.json()
    assert d["status"] == "ASSIGNED" and d["assignee"]["name"] == "Caretaker Hostel A"
    assert d["urgent"] is False and d["escalation_level"] == 0


def test_second_hostel_goes_to_its_own_caretaker(client, world):
    login_as(client, "priya")
    assert new_issue(client, world, unit="Hostel B").json()["assignee"]["name"] == "Caretaker Hostel B"


def test_category_default_route_when_no_unit(client, world):
    login_as(client, "ravi")
    assert new_issue(client, world, unit=None).json()["assignee"]["name"] == "Warden"   # hostel default


def test_fallback_to_other_category_when_route_missing(client, world, db_session):
    cat = world["categories"]["Library"]
    db_session.delete(db_session.scalar(select(Routing).where(Routing.category_id == cat.id)))
    db_session.commit()
    login_as(client, "ravi")
    r = new_issue(client, world, category="Library", unit=None)
    assert r.json()["assignee"]["name"] == "Grievance Cell"


def test_inactive_first_level_skips_to_next(client, world, db_session):
    world["users"]["caretaker_a"].active = False
    db_session.commit()
    login_as(client, "ravi")
    d = new_issue(client, world).json()
    assert d["assignee"]["name"] == "Warden" and d["escalation_level"] == 1


def test_unit_must_match_category(client, world):
    login_as(client, "ravi")
    assert new_issue(client, world, unit="CSE").status_code == 422        # department unit, hostel category


def test_validation(client, world):
    login_as(client, "ravi")
    assert new_issue(client, world, description="hi").status_code == 422
    assert new_issue(client, world, description="x" * 5001).status_code == 422
    assert client.post(f"{API}/issues", json={"description": "valid text here", "category_id": "nope"}).status_code == 422


def test_duplicate_open_ticket_is_refused_with_pointer(client, world):
    login_as(client, "ravi")
    first = issue_id(new_issue(client, world))
    r = new_issue(client, world)
    assert r.status_code == 409 and r.json()["existing_ticket_id"] == first
    client.post(f"{API}/issues/{first}/cancel")
    assert new_issue(client, world).status_code == 201                   # allowed once closed


def test_daily_limit(client, world, settings):
    settings.max_tickets_per_day = 2
    login_as(client, "ravi")
    assert new_issue(client, world, category="Library", unit=None).status_code == 201
    assert new_issue(client, world, category="Transport", unit=None).status_code == 201
    assert new_issue(client, world, category="Fees and accounts", unit=None).status_code == 429


def test_ticket_numbers_are_unique(client, world):
    login_as(client, "ravi")
    a = new_issue(client, world, category="Library", unit=None).json()["ticket_no"]
    b = new_issue(client, world, category="Transport", unit=None).json()["ticket_no"]
    assert a != b


# ---------- confidential ----------

def test_ticked_confidential_goes_to_officers_only(client, world):
    login_as(client, "priya")
    d = new_issue(client, world, category="Library", unit=None, confidential=True).json()
    assert d["confidential"] is True and d["assignee"] is None            # reporter doesn't see handler
    tid = d["id"]
    for who in ("admin", "warden", "librarian", "cell", "ravi"):
        logout(client); login_as(client, who)
        assert client.get(f"{API}/issues/{tid}").status_code == 404, who
    logout(client); login_as(client, "officer1")
    got = client.get(f"{API}/issues/{tid}")
    assert got.status_code == 200 and got.json()["reporter"]["name"] == "Priya Sharma"


def test_confidential_category_routes_to_officer(client, world):
    login_as(client, "priya")
    cat = "Harassment, ragging, discrimination, safety"
    d = new_issue(client, world, category=cat, unit=None).json()
    assert d["confidential"] is True
    logout(client); login_as(client, "officer1")
    assert client.get(f"{API}/staff/issues").json()["total"] == 1


def test_confidential_routing_misconfigured_is_refused(client, world, db_session):
    route = db_session.scalar(select(Routing).where(
        Routing.category_id == world["categories"]["Harassment, ragging, discrimination, safety"].id))
    route.level0_user_id = world["users"]["warden"].id          # not an officer
    route.level1_user_id = None
    db_session.commit()
    login_as(client, "priya")
    assert new_issue(client, world, category="Library", unit=None, confidential=True).status_code == 503


def test_classifier_hook_can_raise_confidential(client, world, monkeypatch):
    monkeypatch.setattr("grievance_app.services.tickets.detect_flags", lambda text: {"confidential": True, "urgent": True})
    login_as(client, "ravi")
    d = new_issue(client, world, category="Library", unit=None, confidential=False).json()
    assert d["confidential"] is True and d["urgent"] is True


# ---------- visibility ----------

def test_other_student_gets_404(client, world):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    logout(client); login_as(client, "priya")
    assert client.get(f"{API}/issues/{tid}").status_code == 404
    assert client.post(f"{API}/issues/{tid}/cancel").status_code == 404
    assert client.get(f"{API}/issues/mine").json()["total"] == 0


def test_my_issues_pagination_and_filter(client, world):
    login_as(client, "ravi")
    for cat in ("Library", "Transport", "Examinations"):
        assert new_issue(client, world, category=cat, unit=None).status_code == 201
    page = client.get(f"{API}/issues/mine?limit=2").json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert client.get(f"{API}/issues/mine?status=CLOSED").json()["total"] == 0
    assert client.get(f"{API}/issues/mine?status=BOGUS").status_code == 422


def test_requires_login_and_csrf(client, world):
    assert client.get(f"{API}/issues/mine").status_code == 401
    login_as(client, "ravi")
    client.headers.pop("X-CSRF-Token")
    assert new_issue(client, world).status_code == 403


# ---------- full lifecycle ----------

def test_full_lifecycle_with_pause_and_feedback(client, world, db_session):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))

    logout(client); login_as(client, "caretaker_a")
    d = client.get(f"{API}/issues/{tid}").json()
    assert d["reporter"]["room"] == "A-101" and "start" in d["actions"]
    assert client.post(f"{API}/issues/{tid}/start").json()["status"] == "IN_PROGRESS"
    assert client.post(f"{API}/issues/{tid}/request-info", json={"text": "Which AC unit?"}).json()["status"] == "NEEDS_INFO"

    # pretend the question was asked 5 hours ago, then the student answers
    t = db_session.get(Ticket, __import__("uuid").UUID(tid))
    due_before = svc.aware(t.due_at)
    t.paused_at = datetime.now(timezone.utc) - timedelta(hours=5)
    db_session.commit()
    logout(client); login_as(client, "ravi")
    r = client.post(f"{API}/issues/{tid}/reply", json={"text": "The one above my bed"})
    assert r.json()["status"] == "IN_PROGRESS"
    db_session.refresh(t)
    assert svc.aware(t.due_at) - due_before > timedelta(hours=4, minutes=55)   # clock resumed with the pause added
    assert t.paused_at is None

    logout(client); login_as(client, "caretaker_a")
    assert client.post(f"{API}/issues/{tid}/resolve", json={"note": "Replaced the capacitor"}).json()["status"] == "RESOLVED"

    logout(client); login_as(client, "ravi")
    assert client.post(f"{API}/issues/{tid}/feedback", json={"rating": 5}).status_code == 409   # not closed yet
    assert client.post(f"{API}/issues/{tid}/confirm").json()["status"] == "CLOSED"
    assert client.post(f"{API}/issues/{tid}/feedback", json={"rating": 5, "comment": "Fast"}).status_code == 201
    assert client.post(f"{API}/issues/{tid}/feedback", json={"rating": 4}).status_code == 409   # only once
    final = client.get(f"{API}/issues/{tid}").json()
    assert final["feedback"]["rating"] == 5 and final["actions"] == []
    assert [e["to_status"] for e in final["events"] if e["to_status"]] == [
        "ASSIGNED", "IN_PROGRESS", "NEEDS_INFO", "IN_PROGRESS", "RESOLVED", "CLOSED"]


def test_reopen_returns_to_first_level_with_new_deadline(client, world, db_session):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    logout(client); login_as(client, "warden")
    client.post(f"{API}/issues/{tid}/resolve", json={"note": "Fixed"})
    logout(client); login_as(client, "ravi")
    assert client.post(f"{API}/issues/{tid}/reopen", json={}).status_code == 422          # reason required
    d = client.post(f"{API}/issues/{tid}/reopen", json={"reason": "Still hot"}).json()
    assert d["status"] == "ASSIGNED" and d["assignee"]["name"] == "Caretaker Hostel A" and d["escalation_level"] == 0


def test_cancel_rules(client, world):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    logout(client); login_as(client, "warden")
    client.post(f"{API}/issues/{tid}/resolve", json={"note": "Done"})
    logout(client); login_as(client, "ravi")
    assert client.post(f"{API}/issues/{tid}/cancel").status_code == 409                   # resolved: use "not fixed"
    client.post(f"{API}/issues/{tid}/confirm")
    assert client.post(f"{API}/issues/{tid}/cancel").status_code == 409                   # closed


def test_illegal_moves_are_409(client, world):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    logout(client); login_as(client, "caretaker_a")
    client.post(f"{API}/issues/{tid}/start")
    assert client.post(f"{API}/issues/{tid}/start").status_code == 409                    # already in progress
    client.post(f"{API}/issues/{tid}/resolve", json={"note": "ok"})
    assert client.post(f"{API}/issues/{tid}/resolve", json={"note": "again"}).status_code == 409
    assert client.post(f"{API}/issues/{tid}/request-info", json={"text": "?"}).status_code == 409


def test_reply_on_resolved_is_refused(client, world):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    logout(client); login_as(client, "warden")
    client.post(f"{API}/issues/{tid}/resolve", json={"note": "Done"})
    logout(client); login_as(client, "ravi")
    assert client.post(f"{API}/issues/{tid}/reply", json={"text": "hello"}).status_code == 409


# ---------- who may do what (403 vs 404) ----------

def test_permissions_on_actions(client, world):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    # the reporter cannot work the ticket
    for path, body in (("start", None), ("resolve", {"note": "x"}), ("request-info", {"text": "x"}),
                       ("escalate", {"reason": "x"})):
        r = client.post(f"{API}/issues/{tid}/{path}", json=body) if body else client.post(f"{API}/issues/{tid}/{path}")
        assert r.status_code == 403, path
    logout(client); login_as(client, "caretaker_b")
    assert client.post(f"{API}/issues/{tid}/start").status_code == 404                  # other hostel: cannot even see it
    logout(client); login_as(client, "caretaker_a")
    assert client.post(f"{API}/issues/{tid}/escalate", json={"reason": "x"}).status_code == 403   # level 0 cannot escalate by hand
    assert client.post(f"{API}/issues/{tid}/cancel").status_code == 403                  # not the reporter
    assert client.post(f"{API}/issues/{tid}/confirm").status_code == 403


def test_conflict_of_interest(client, world):
    login_as(client, "caretaker_a")                     # the caretaker reports a problem in their own hostel
    tid = issue_id(new_issue(client, world))
    assert client.post(f"{API}/issues/{tid}/start").status_code == 403
    logout(client); login_as(client, "warden")
    assert client.post(f"{API}/issues/{tid}/start").status_code == 200


# ---------- escalate and reassign ----------

def test_manual_escalation_chain(client, world):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    logout(client); login_as(client, "warden")
    d = client.post(f"{API}/issues/{tid}/escalate", json={"reason": "No response"}).json()
    assert d["status"] == "ESCALATED" and d["escalation_level"] == 1 and d["assignee"]["name"] == "Warden"
    d = client.post(f"{API}/issues/{tid}/escalate", json={"reason": "Still nothing"}).json()
    assert d["escalation_level"] == 2 and d["assignee"]["name"] == "Chief Warden"
    assert client.post(f"{API}/issues/{tid}/escalate", json={"reason": "again"}).status_code == 409   # top level
    assert "escalate" not in client.get(f"{API}/issues/{tid}").json()["actions"]


def test_admin_can_escalate_normal_but_not_resolve(client, world):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    logout(client); login_as(client, "admin")
    assert client.post(f"{API}/issues/{tid}/resolve", json={"note": "x"}).status_code == 403
    assert client.post(f"{API}/issues/{tid}/escalate", json={"reason": "x"}).status_code == 200


def test_escalation_of_confidential_stays_with_officers(client, world):
    login_as(client, "priya")
    cat = "Harassment, ragging, discrimination, safety"
    tid = issue_id(new_issue(client, world, category=cat, unit=None))
    logout(client); login_as(client, "officer1")
    d = client.post(f"{API}/issues/{tid}/escalate", json={"reason": "Needs senior officer"}).json()
    assert d["assignee"]["name"] == "Designated Officer 2"
    logout(client); login_as(client, "admin")
    assert client.post(f"{API}/issues/{tid}/escalate", json={"reason": "x"}).status_code == 404


def test_reassign(client, world):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    logout(client); login_as(client, "warden")
    body = {"assignee_id": str(world["users"]["caretaker_b"].id), "reason": "Caretaker A on leave"}
    assert client.post(f"{API}/issues/{tid}/reassign", json=body).json()["assignee"]["name"] == "Caretaker Hostel B"
    same = client.post(f"{API}/issues/{tid}/reassign", json=body)
    assert same.status_code == 422                                                 # already theirs
    to_student = {"assignee_id": str(world["users"]["priya"].id), "reason": "x"}
    assert client.post(f"{API}/issues/{tid}/reassign", json=to_student).status_code == 422
    # the reassignment is internal: the student does not see it, staff do
    staff_events = client.get(f"{API}/issues/{tid}").json()["events"]
    assert any(e["type"] == "assignment" and e["internal"] for e in staff_events)
    logout(client); login_as(client, "ravi")
    assert all(e["type"] != "assignment" for e in client.get(f"{API}/issues/{tid}").json()["events"])


def test_reassign_confidential_only_to_officers(client, world):
    login_as(client, "priya")
    tid = issue_id(new_issue(client, world, category="Harassment, ragging, discrimination, safety", unit=None))
    logout(client); login_as(client, "officer1")
    bad = {"assignee_id": str(world["users"]["warden"].id), "reason": "x"}
    assert client.post(f"{API}/issues/{tid}/reassign", json=bad).status_code == 422


def test_timeline_labels_for_confidential_reporter(client, world):
    login_as(client, "priya")
    tid = issue_id(new_issue(client, world, category="Harassment, ragging, discrimination, safety", unit=None))
    logout(client); login_as(client, "officer1")
    client.post(f"{API}/issues/{tid}/start")
    logout(client); login_as(client, "priya")
    events = client.get(f"{API}/issues/{tid}").json()["events"]
    assert events[-1]["actor"] == "Designated officer"


# ---------- notification hook ----------

def test_notify_hook_called_in_order(client, world, monkeypatch):
    calls = []
    for mod in ("grievance_app.services.tickets",):
        monkeypatch.setattr(f"{mod}.notify", lambda db, kind, ticket, **kw: calls.append(kind))
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    logout(client); login_as(client, "caretaker_a")
    client.post(f"{API}/issues/{tid}/request-info", json={"text": "?"})
    logout(client); login_as(client, "ravi")
    client.post(f"{API}/issues/{tid}/reply", json={"text": "answer"})
    logout(client); login_as(client, "warden")
    client.post(f"{API}/issues/{tid}/escalate", json={"reason": "slow"})
    client.post(f"{API}/issues/{tid}/resolve", json={"note": "done"})
    logout(client); login_as(client, "ravi")
    client.post(f"{API}/issues/{tid}/confirm")
    assert calls == ["created", "info_requested", "replied", "escalated", "resolved", "closed"]


# ---------- automatic closing and the escalation helper (used by Stage 3) ----------

def test_auto_close(client, world, db_session):
    login_as(client, "ravi")
    a = issue_id(new_issue(client, world, category="Library", unit=None))
    b = issue_id(new_issue(client, world, category="Transport", unit=None))
    logout(client); login_as(client, "priya")
    c = issue_id(new_issue(client, world, category="Harassment, ragging, discrimination, safety", unit=None))
    import uuid
    now = datetime.now(timezone.utc)
    ta, tb, tc = (db_session.get(Ticket, uuid.UUID(x)) for x in (a, b, c))
    ta.status, ta.resolved_at = "RESOLVED", now - timedelta(days=4)
    tb.status, tb.paused_at = "NEEDS_INFO", now - timedelta(days=8)
    tc.status, tc.resolved_at = "RESOLVED", now - timedelta(days=30)               # confidential: never auto-closed
    db_session.commit()
    assert svc.auto_close(db_session, now) == 2
    db_session.refresh(ta); db_session.refresh(tb); db_session.refresh(tc)
    assert (ta.status, tb.status, tc.status) == ("CLOSED", "CLOSED", "RESOLVED")
    last = db_session.scalars(select(Event).where(Event.ticket_id == ta.id).order_by(Event.created_at.desc())).first()
    assert "automatically" in last.text and last.actor_id is None


def test_system_escalation_and_overdue_clause(client, world, db_session):
    login_as(client, "ravi")
    tid = issue_id(new_issue(client, world))
    import uuid
    t = db_session.get(Ticket, uuid.UUID(tid))
    future = datetime.now(timezone.utc) + timedelta(hours=30)
    assert db_session.scalars(select(Ticket).where(svc.overdue_clause(future))).all() == [t]
    assert db_session.scalars(select(Ticket).where(svc.overdue_clause())).all() == []
    svc.escalate_ticket(db_session, t, None, "Deadline missed", now=future)
    assert (t.status, t.escalation_level, t.assignee_id) == ("ESCALATED", 1, world["users"]["warden"].id)
    svc.escalate_ticket(db_session, t, None, "Deadline missed", now=future)            # second automatic escalation
    assert t.escalation_level == 2
