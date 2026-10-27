import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from grievance_app.models import Event, Notification, SystemState, Ticket
from grievance_app.services import scheduler
from grievance_app.services.state import get_state, set_state
from grievance_app.services import tickets as svc
from tests.grievance.conftest import login_as, logout, new_issue

API = "/api/grievance"
CONF_CAT = "Harassment, ragging, discrimination, safety"


def make_ticket(client, world, who="ravi", **kw):
    logout(client); login_as(client, who)
    r = new_issue(client, world, **kw)
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


def later(hours):
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def ev(db, tid, type_=None):
    q = select(Event).where(Event.ticket_id == tid)
    if type_:
        q = q.where(Event.type == type_)
    return db.scalars(q.order_by(Event.created_at)).all()


# ---------- escalation ----------

def test_overdue_ticket_is_escalated_once(client, world, db_session):
    tid = make_ticket(client, world)
    assert scheduler.run_escalations(db_session, later(1)) == 0                  # not overdue yet (24 h)
    assert scheduler.run_escalations(db_session, later(25)) == 1
    t = db_session.get(Ticket, tid)
    assert (t.status, t.escalation_level, t.assignee_id) == ("ESCALATED", 1, world["users"]["warden"].id)
    assert svc.aware(t.due_at) > later(40)                                       # new 24 h deadline
    assert scheduler.run_escalations(db_session, later(25)) == 0                 # running again changes nothing
    last = ev(db_session, tid)[-1]
    assert last.actor_id is None and "Escalated automatically" in last.text and last.visible_to_student


def test_second_deadline_goes_to_next_level_then_stops(client, world, db_session):
    tid = make_ticket(client, world)
    scheduler.run_escalations(db_session, later(25))
    scheduler.run_escalations(db_session, later(60))
    assert db_session.get(Ticket, tid).escalation_level == 2
    assert db_session.get(Ticket, tid).assignee_id == world["users"]["chief_warden"].id
    # top level: nobody higher. One internal event per missed deadline, ticket stays overdue
    assert scheduler.escalate_if_overdue(db_session, tid, later(100)) == "top_level"
    assert scheduler.escalate_if_overdue(db_session, tid, later(101)) == "skipped"
    assert len(ev(db_session, tid, "overdue_top")) == 1
    assert ev(db_session, tid, "overdue_top")[0].visible_to_student is False
    assert any("past its deadline" in n.text for n in db_session.scalars(select(Notification).where(
        Notification.user_id == world["users"]["chief_warden"].id)).all())
    assert db_session.scalar(select(Ticket.id).where(svc.overdue_clause(later(101)))) == tid


def test_two_runs_at_the_same_time_escalate_only_once(client, world, db_session, monkeypatch):
    """Simulate a second worker escalating between our read and our update."""
    tid = make_ticket(client, world)
    real = scheduler.next_level
    def racing(db, route, level, officers_only=False):
        result = real(db, route, level, officers_only)
        db.execute(update(Ticket).where(Ticket.id == tid).values(escalation_level=1))   # the other worker wins
        db.commit()
        return result
    monkeypatch.setattr(scheduler, "next_level", racing)
    assert scheduler.escalate_if_overdue(db_session, tid, later(25)) == "skipped"
    assert len(ev(db_session, tid, "status")) == 1                                       # only the creation event


def test_inactive_next_level_is_skipped(client, world, db_session):
    tid = make_ticket(client, world)
    world["users"]["warden"].active = False
    db_session.commit()
    scheduler.run_escalations(db_session, later(25))
    assert db_session.get(Ticket, tid).assignee_id == world["users"]["chief_warden"].id


def test_paused_and_final_tickets_are_not_escalated(client, world, db_session):
    a = make_ticket(client, world, category="Library", unit=None)
    b = make_ticket(client, world, category="Transport", unit=None)
    db_session.get(Ticket, a).status = "NEEDS_INFO"
    db_session.get(Ticket, b).status = "RESOLVED"
    db_session.commit()
    assert scheduler.run_escalations(db_session, later(500)) == 0


def test_confidential_escalates_only_within_officers(client, world, db_session):
    tid = make_ticket(client, world, "priya", category=CONF_CAT, unit=None)
    scheduler.run_escalations(db_session, later(25))
    t = db_session.get(Ticket, tid)
    assert t.assignee_id == world["users"]["officer2"].id
    assert scheduler.escalate_if_overdue(db_session, tid, later(60)) == "top_level"     # no third officer
    assert db_session.get(Ticket, tid).assignee_id == world["users"]["officer2"].id


def test_confidential_never_escalates_to_a_non_officer(client, world, db_session):
    from grievance_app.models import Routing
    tid = make_ticket(client, world, "priya", category=CONF_CAT, unit=None)
    route = db_session.get(Routing, db_session.get(Ticket, tid).route_id)
    route.level1_user_id, route.level2_user_id = world["users"]["warden"].id, None     # misconfigured
    db_session.commit()
    assert scheduler.escalate_if_overdue(db_session, tid, later(25)) == "top_level"
    logout(client); login_as(client, "officer1")
    assert client.post(f"{API}/issues/{tid}/escalate", json={"reason": "x"}).status_code == 409   # manual too


def test_escalation_notifies_new_previous_and_reporter(client, world, db_session):
    make_ticket(client, world)
    scheduler.run_escalations(db_session, later(25))
    def last(key):
        return db_session.scalars(select(Notification).where(Notification.user_id == world["users"][key].id)
                                  .order_by(Notification.created_at.desc())).first().text
    assert "was escalated to you" in last("warden")
    assert "was escalated to Warden" in last("caretaker_a")
    assert "passed to a senior person" in last("ravi")


# ---------- auto close and run_once ----------

def test_run_once_does_everything_and_records_heartbeat(client, world, db_session):
    a = make_ticket(client, world)
    b = make_ticket(client, world, category="Library", unit=None)
    tb = db_session.get(Ticket, b)
    tb.status, tb.resolved_at = "RESOLVED", later(-24 * 4)
    db_session.commit()
    now = later(25)
    summary = scheduler.run_once(db_session, now)
    assert summary["escalated"] == 1 and summary["auto_closed"] == 1 and "emails" in summary
    assert db_session.get(Ticket, b).status == "CLOSED"
    assert get_state(db_session, scheduler.HEARTBEAT) is not None
    assert scheduler.heartbeat_age_minutes(db_session, now) < 1


def test_one_failing_job_does_not_stop_the_others(client, world, db_session, monkeypatch):
    make_ticket(client, world)
    monkeypatch.setattr(scheduler, "auto_close", lambda db, now: (_ for _ in ()).throw(RuntimeError("boom")))
    summary = scheduler.run_once(db_session, later(25))
    assert summary["auto_closed"] == "error" and summary["escalated"] == 1
    assert "auto_closed: RuntimeError" in get_state(db_session, "scheduler_last_error")
    assert get_state(db_session, scheduler.HEARTBEAT) is not None


# ---------- email outbox ----------

class Mailbox:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, to, subject, body):
        if self.fail:
            raise ConnectionError("smtp down")
        self.sent.append((to, subject, body))


@pytest.fixture()
def mail(settings):
    settings.smtp_host = "smtp.test"
    settings.app_base_url = "https://college.test"
    return Mailbox()


def test_emails_are_sent_with_a_link(client, world, db_session, mail):
    tid = make_ticket(client, world)
    r = scheduler.process_email_outbox(db_session, later(0), mail)
    assert r == {"sent": 2, "failed": 0}
    to = {m[0] for m in mail.sent}
    assert to == {"ravi@college.edu", "caretaker_a@college.edu"}
    body = [m for m in mail.sent if m[0] == "ravi@college.edu"][0]
    assert "GRV-" in body[1] and f"https://college.test/grievance/issues/{tid}" in body[2]
    assert all(n.email_sent for n in db_session.scalars(select(Notification)).all())
    assert scheduler.process_email_outbox(db_session, later(0), mail) == {"sent": 0, "failed": 0}   # nothing twice


def test_confidential_emails_are_content_free(client, world, db_session, mail):
    make_ticket(client, world, "priya", category=CONF_CAT, unit=None)
    scheduler.process_email_outbox(db_session, later(0), mail)
    assert len(mail.sent) == 2
    for to, subject, body in mail.sent:
        assert subject == "Grievance system: update available"
        assert "GRV-" not in body and "Harassment" not in body and "ragging" not in body.lower()


def test_failed_email_is_recorded_and_retried_later(client, world, db_session, settings):
    settings.smtp_host = "smtp.test"
    make_ticket(client, world)
    broken = Mailbox(fail=True)
    r = scheduler.process_email_outbox(db_session, later(0), broken)
    assert r == {"sent": 0, "failed": 2}
    n = db_session.scalars(select(Notification)).first()
    assert n.email_attempts == 1 and "smtp down" in n.email_error and not n.email_sent
    assert scheduler.process_email_outbox(db_session, later(1 / 60), broken) == {"sent": 0, "failed": 0}   # too soon
    good = Mailbox()
    assert scheduler.process_email_outbox(db_session, later(0.2), good) == {"sent": 2, "failed": 0}       # retried
    db_session.refresh(n)
    assert n.email_sent and n.email_error is None


def test_gives_up_after_max_attempts(client, world, db_session, settings):
    settings.smtp_host = "smtp.test"
    settings.email_max_attempts = 2
    make_ticket(client, world)
    broken = Mailbox(fail=True)
    for i in range(4):
        scheduler.process_email_outbox(db_session, later(1 + i), broken)
    assert {n.email_attempts for n in db_session.scalars(select(Notification)).all()} == {2}


def test_email_not_configured_gives_up_quietly(client, world, db_session, settings):
    settings.smtp_host = ""
    make_ticket(client, world)
    r = scheduler.process_email_outbox(db_session, later(0), Mailbox())
    assert r["sent"] == 0 and r["gave_up"] == 2
    assert {n.email_error for n in db_session.scalars(select(Notification)).all()} == {"Email is not configured"}
    settings.smtp_host = "smtp.test"
    assert scheduler.process_email_outbox(db_session, later(10), Mailbox()) == {"sent": 0, "failed": 0}   # no flood later


def test_user_without_email_is_recorded_not_fatal(client, world, db_session, mail):
    make_ticket(client, world)
    world["users"]["ravi"].email = ""
    db_session.commit()
    r = scheduler.process_email_outbox(db_session, later(0), mail)
    assert r == {"sent": 1, "failed": 1}


# ---------- watchdog ----------

def test_watchdog_alerts_once_per_outage(db_session, world, settings, mail):
    settings.heartbeat_alert_minutes = 60
    settings.admin_alert_email = "it-cell@college.edu"
    t0 = datetime.now(timezone.utc)
    set_state(db_session, scheduler.HEARTBEAT, t0.isoformat())
    assert scheduler.check_heartbeat(db_session, t0 + timedelta(minutes=30), mail) is False        # fresh
    assert scheduler.check_heartbeat(db_session, t0 + timedelta(minutes=61), mail) is True
    assert mail.sent[0][0] == "it-cell@college.edu" and "not running" in mail.sent[0][1]
    assert scheduler.check_heartbeat(db_session, t0 + timedelta(minutes=120), mail) is False       # same outage
    set_state(db_session, scheduler.HEARTBEAT, (t0 + timedelta(minutes=130)).isoformat())          # worker came back
    assert scheduler.check_heartbeat(db_session, t0 + timedelta(minutes=150), mail) is False       # healthy again


def test_watchdog_alerts_again_after_a_new_outage(db_session, world, settings, mail):
    settings.heartbeat_alert_minutes = 60
    settings.admin_alert_email = "it-cell@college.edu"
    t0 = datetime.now(timezone.utc)
    set_state(db_session, scheduler.HEARTBEAT, t0.isoformat())
    assert scheduler.check_heartbeat(db_session, t0 + timedelta(minutes=70), mail) is True
    set_state(db_session, scheduler.HEARTBEAT, (t0 + timedelta(minutes=80)).isoformat())
    assert scheduler.check_heartbeat(db_session, t0 + timedelta(minutes=200), mail) is True
    assert len(mail.sent) == 2


def test_watchdog_defaults_to_admin_emails_and_handles_never_ran(db_session, world, settings, mail):
    settings.heartbeat_alert_minutes = 10
    t0 = datetime.now(timezone.utc)
    assert scheduler.check_heartbeat(db_session, t0, mail) is False                 # starts watching now
    assert scheduler.check_heartbeat(db_session, t0 + timedelta(minutes=11), mail) is True
    assert [m[0] for m in mail.sent] == ["admin@college.edu"]


def test_watchdog_without_email_does_not_crash(db_session, world, settings):
    settings.smtp_host = ""
    settings.heartbeat_alert_minutes = 1
    t0 = datetime.now(timezone.utc)
    scheduler.check_heartbeat(db_session, t0, None)
    assert scheduler.check_heartbeat(db_session, t0 + timedelta(minutes=5), None) is False
