from sqlalchemy import select

from grievance_app.models import Notification, Ticket
from tests.grievance.conftest import login_as, logout, new_issue

API = "/api/grievance"


def notes(db, world, key):
    user = world["users"][key]
    return [n.text for n in db.scalars(select(Notification).where(Notification.user_id == user.id)
                                       .order_by(Notification.created_at)).all()]


def test_created_notifies_reporter_and_assignee(client, world, db_session):
    login_as(client, "ravi")
    no = new_issue(client, world).json()["ticket_no"]
    assert notes(db_session, world, "ravi") == [f"We received your problem. Your ticket number is {no}."]
    assert notes(db_session, world, "caretaker_a") == [f"New ticket {no} (Hostel and housing) is assigned to you."]
    assert notes(db_session, world, "warden") == []


def test_people_are_not_notified_about_their_own_actions(client, world, db_session):
    login_as(client, "ravi")
    tid = new_issue(client, world).json()["id"]
    logout(client); login_as(client, "caretaker_a")
    client.post(f"{API}/issues/{tid}/request-info", json={"text": "Which unit?"})
    assert len(notes(db_session, world, "caretaker_a")) == 1               # only the original assignment
    logout(client); login_as(client, "ravi")
    client.post(f"{API}/issues/{tid}/reply", json={"text": "The left one"})
    assert "replied" in notes(db_session, world, "caretaker_a")[-1]
    assert len(notes(db_session, world, "ravi")) == 2                       # received + info requested


def test_escalation_notifies_three_people(client, world, db_session):
    login_as(client, "ravi")
    tid = new_issue(client, world).json()["id"]
    logout(client); login_as(client, "warden")
    client.post(f"{API}/issues/{tid}/escalate", json={"reason": "Slow"})
    assert any("escalated to you" in t for t in notes(db_session, world, "warden")) is False   # actor excluded
    # chain: caretaker (previous) -> warden (new)
    assert any("was escalated to Warden" in t for t in notes(db_session, world, "caretaker_a"))
    assert any("passed to a senior person" in t for t in notes(db_session, world, "ravi"))


def test_resolved_closed_cancelled_reopened(client, world, db_session):
    login_as(client, "ravi")
    tid = new_issue(client, world).json()["id"]
    logout(client); login_as(client, "caretaker_a")
    client.post(f"{API}/issues/{tid}/resolve", json={"note": "Fixed"})
    assert "marked as resolved" in notes(db_session, world, "ravi")[-1]
    logout(client); login_as(client, "ravi")
    client.post(f"{API}/issues/{tid}/reopen", json={"reason": "No"})
    assert "reopened" in notes(db_session, world, "caretaker_a")[-1]
    logout(client); login_as(client, "caretaker_a")
    client.post(f"{API}/issues/{tid}/resolve", json={"note": "Really fixed"})
    logout(client); login_as(client, "ravi")
    client.post(f"{API}/issues/{tid}/confirm")
    assert "tell us how we did" in notes(db_session, world, "ravi")[-1]
    tid2 = new_issue(client, world, category="Library", unit=None).json()["id"]
    client.post(f"{API}/issues/{tid2}/cancel")
    assert "cancelled by the reporter" in notes(db_session, world, "librarian")[-1]


def test_reassign_notifies_new_assignee(client, world, db_session):
    login_as(client, "ravi")
    tid = new_issue(client, world).json()["id"]
    logout(client); login_as(client, "warden")
    client.post(f"{API}/issues/{tid}/reassign", json={"assignee_id": str(world["users"]["caretaker_b"].id), "reason": "Leave"})
    assert "was assigned to you" in notes(db_session, world, "caretaker_b")[-1]


def test_urgent_prefix(client, world, db_session):
    login_as(client, "ravi")
    new_issue(client, world, description="Sparking and a short circuit in the switch board of my room")
    assert notes(db_session, world, "caretaker_a")[-1].startswith("[URGENT] ")


def test_confidential_notifications_are_content_free(client, world, db_session):
    login_as(client, "priya")
    d = new_issue(client, world, category="Harassment, ragging, discrimination, safety", unit=None).json()
    texts = notes(db_session, world, "priya") + notes(db_session, world, "officer1")
    assert texts == ["There is an update on your ticket. Log in to view it.",
                     "A restricted ticket needs your attention. Log in to view it."]
    for t in texts:
        assert "GRV" not in t and "Harassment" not in t
    logout(client); login_as(client, "officer1")
    client.post(f"{API}/issues/{d['id']}/resolve", json={"note": "Handled"})
    assert notes(db_session, world, "priya")[-1] == "There is an update on your ticket. Log in to view it."
    # nobody else (admin, warden) received anything
    assert notes(db_session, world, "admin") == [] and notes(db_session, world, "warden") == []


def test_inactive_users_are_skipped(client, world, db_session):
    login_as(client, "ravi")
    world["users"]["caretaker_a"].active = False
    db_session.commit()
    new_issue(client, world)
    assert notes(db_session, world, "caretaker_a") == []


def test_notification_failure_never_breaks_the_action(client, world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database hiccup")
    monkeypatch.setattr("grievance_app.services.notify._recipients", boom)
    login_as(client, "ravi")
    assert new_issue(client, world).status_code == 201


# ---------- endpoints ----------

def test_notification_endpoints(client, world, db_session):
    login_as(client, "ravi")
    new_issue(client, world)
    new_issue(client, world, category="Library", unit=None)
    page = client.get(f"{API}/notifications").json()
    assert page["total"] == 2 and page["unread"] == 2 and len(page["items"]) == 2
    assert client.get(f"{API}/notifications/unread-count").json() == {"unread": 2}
    nid = page["items"][0]["id"]
    assert client.post(f"{API}/notifications/{nid}/read").json()["read"] is True
    assert client.get(f"{API}/notifications?unread_only=true").json()["total"] == 1
    assert client.post(f"{API}/notifications/read-all").status_code == 200
    assert client.get(f"{API}/notifications/unread-count").json() == {"unread": 0}


def test_other_users_notification_is_404(client, world, db_session):
    login_as(client, "ravi")
    new_issue(client, world)
    nid = client.get(f"{API}/notifications").json()["items"][0]["id"]
    logout(client); login_as(client, "priya")
    assert client.post(f"{API}/notifications/{nid}/read").status_code == 404
    assert client.get(f"{API}/notifications").json()["total"] == 0


def test_notifications_require_login(client):
    assert client.get(f"{API}/notifications").status_code == 401
