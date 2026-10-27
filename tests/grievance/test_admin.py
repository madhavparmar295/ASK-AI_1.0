import io

import pytest
from sqlalchemy import select

from grievance_app.models import AuditLog, Category, Routing, Ticket, Unit, User
from tests.grievance.conftest import login_as, logout, new_issue

API = "/api/grievance"
CONF = "Harassment, ragging, discrimination, safety"


def uid(world, key):
    return str(world["users"][key].id)


def csv_file(text, name="data.csv"):
    return {"file": (name, io.BytesIO(text.encode()), "text/csv")}


@pytest.fixture()
def admin(client, world):
    login_as(client, "admin")
    return client


# ---------- access ----------

ADMIN_GETS = ["/admin/categories", "/admin/units", "/admin/routing", "/admin/users", "/admin/audit",
              "/admin/stats", "/admin/issues", "/admin/health", "/admin/routing/template", "/admin/users/template"]


@pytest.mark.parametrize("who", ["ravi", "warden", "officer1", "cell"])
def test_only_admin_reaches_admin_endpoints(client, world, who):
    login_as(client, who)
    for path in ADMIN_GETS:
        assert client.get(API + path).status_code == 404, (who, path)
    assert client.post(f"{API}/admin/categories", json={"name": "X"}).status_code == 404
    assert client.post(f"{API}/admin/users/import", files=csv_file("name,email\n")).status_code == 404


def test_admin_endpoints_need_login(client):
    assert client.get(f"{API}/admin/stats").status_code == 401


# ---------- categories ----------

def test_category_crud_and_audit(admin, world, db_session):
    assert len(admin.get(f"{API}/admin/categories").json()) == 12
    r = admin.post(f"{API}/admin/categories", json={"name": "Sports", "sla_hours": 48, "keywords": "cricket, football:2"})
    assert r.status_code == 201 and r.json()["unit_type"] == "campus"
    cid = r.json()["id"]
    assert admin.post(f"{API}/admin/categories", json={"name": "sports"}).status_code == 409       # case-insensitive
    p = admin.patch(f"{API}/admin/categories/{cid}", json={"sla_hours": 24, "active": False})
    assert p.json()["sla_hours"] == 24 and p.json()["active"] is False
    assert admin.post(f"{API}/admin/categories", json={"name": "Z", "sla_hours": 0}).status_code == 422
    assert admin.patch(f"{API}/admin/categories/{cid}", json={"name": "Library"}).status_code == 409
    actions = [(a.action, a.entity) for a in db_session.scalars(select(AuditLog).order_by(AuditLog.created_at)).all()]
    assert actions == [("create", "category"), ("update", "category")]


def test_keywords_edited_by_admin_change_suggestions(admin, world):
    cid = str(world["categories"]["Transport"].id)
    admin.patch(f"{API}/admin/categories/{cid}", json={"keywords": "ferry:5"})
    assert admin.post(f"{API}/classify", json={"text": "the ferry is late"}).json()["suggested"]["name"] == "Transport"


def test_fallback_category_is_protected(admin, world):
    cid = str(world["categories"]["Other"].id)
    for body in ({"name": "Misc"}, {"active": False}, {"confidential": True}):
        assert admin.patch(f"{API}/admin/categories/{cid}", json=body).status_code == 409
    assert admin.patch(f"{API}/admin/categories/{cid}", json={"sla_hours": 96}).status_code == 200


def test_last_confidential_category_is_protected(admin, world):
    cid = str(world["categories"][CONF].id)
    assert admin.patch(f"{API}/admin/categories/{cid}", json={"active": False}).status_code == 409
    assert admin.patch(f"{API}/admin/categories/{cid}", json={"confidential": False}).status_code == 409
    # add a second confidential category with a route, then the first may be switched off
    new = admin.post(f"{API}/admin/categories", json={"name": "Safety", "confidential": True}).json()["id"]
    admin.post(f"{API}/admin/routing", json={"category_id": new, "level0_user_id": uid(world, "officer1")})
    assert admin.patch(f"{API}/admin/categories/{cid}", json={"active": False}).status_code == 200


def test_cannot_change_unit_type_while_routes_use_old_type(admin, world):
    cid = str(world["categories"]["Hostel and housing"].id)
    assert admin.patch(f"{API}/admin/categories/{cid}", json={"unit_type": "department"}).status_code == 409


def test_unknown_category_id_is_404(admin):
    import uuid
    assert admin.patch(f"{API}/admin/categories/{uuid.uuid4()}", json={"active": False}).status_code == 404


# ---------- units ----------

def test_units(admin, world, client):
    r = admin.post(f"{API}/admin/units", json={"name": "Hostel C", "type": "hostel"})
    assert r.status_code == 201 and r.json()["routes"] == 0
    assert admin.post(f"{API}/admin/units", json={"name": "hostel c", "type": "hostel"}).status_code == 409
    assert admin.post(f"{API}/admin/units", json={"name": "Hostel C", "type": "department"}).status_code == 201
    uid_ = r.json()["id"]
    assert admin.patch(f"{API}/admin/units/{uid_}", json={"name": "Hostel D"}).json()["name"] == "Hostel D"
    assert admin.patch(f"{API}/admin/units/{uid_}", json={"name": "Hostel A"}).status_code == 409
    hostels = admin.get(f"{API}/admin/units?type=hostel").json()
    assert {u["name"] for u in hostels} == {"Hostel A", "Hostel B", "Hostel D"}
    assert next(u for u in hostels if u["name"] == "Hostel A")["routes"] == 1
    # deactivated locations can no longer be chosen for tickets
    admin.patch(f"{API}/admin/units/{uid_}", json={"active": False})
    logout(client); login_as(client, "ravi")
    body = {"description": "Fan is broken in my room", "category_id": str(world["categories"]["Hostel and housing"].id),
            "unit_id": uid_}
    assert client.post(f"{API}/issues", json=body).status_code == 422


# ---------- routing ----------

def test_route_validation(admin, world):
    cat = str(world["categories"]["Library"].id)
    conf = str(world["categories"][CONF].id)
    hostel_cat = str(world["categories"]["Hostel and housing"].id)

    def post(**kw):
        body = {"category_id": cat, "level0_user_id": uid(world, "librarian")}
        body.update(kw)
        return admin.post(f"{API}/admin/routing", json=body)

    assert post(level0_user_id=uid(world, "ravi")).status_code == 422                       # student cannot handle
    assert post(level1_user_id=uid(world, "librarian")).status_code == 422                  # same person twice
    assert post(level2_user_id=uid(world, "registrar")).status_code == 422                  # level 2 without level 1
    assert post(unit_id=str(world["units"]["Hostel A"].id)).status_code == 422              # wrong location type
    r = post(category_id=conf, level0_user_id=uid(world, "warden"))
    assert r.status_code == 422 and "not a designated officer" in r.json()["detail"]
    assert post(level0_user_id=uid(world, "librarian")).status_code == 409                  # route already exists
    admin.patch(f"{API}/admin/users/{uid(world, 'registrar')}", json={"active": False})
    r = post(category_id=str(world["categories"]["Transport"].id), level0_user_id=uid(world, "registrar"))
    assert r.status_code == 422 and "deactivated" in r.json()["detail"]


def test_create_edit_delete_route_and_effect_on_new_tickets(admin, world, client):
    cat = admin.post(f"{API}/admin/categories", json={"name": "Sports", "unit_type": "campus"}).json()["id"]
    r = admin.post(f"{API}/admin/routing", json={"category_id": cat, "level0_user_id": uid(world, "librarian"),
                                                 "level1_user_id": uid(world, "registrar")})
    assert r.status_code == 201 and r.json()["level0"]["email"] == "librarian@college.edu"
    rid = r.json()["id"]

    def ticket():
        logout(client); login_as(client, "ravi")
        return client.post(f"{API}/issues", json={"description": "Ground is not usable", "category_id": cat}).json()

    t1 = ticket()
    assert t1["assignee"]["name"] == "Librarian"
    logout(client); login_as(client, "admin")
    assert admin.patch(f"{API}/admin/routing/{rid}", json={"level0_user_id": uid(world, "transport")}).status_code == 200
    logout(client); login_as(client, "ravi")
    client.post(f"{API}/issues/{t1['id']}/cancel")
    assert client.post(f"{API}/issues", json={"description": "Ground is not usable", "category_id": cat}).json()["assignee"]["name"] == "Transport In-charge"
    logout(client); login_as(client, "admin")
    assert admin.delete(f"{API}/admin/routing/{rid}").status_code == 409                    # tickets use it
    spare = admin.post(f"{API}/admin/categories", json={"name": "Spare"}).json()["id"]
    sr = admin.post(f"{API}/admin/routing", json={"category_id": spare, "level0_user_id": uid(world, "librarian")}).json()["id"]
    assert admin.delete(f"{API}/admin/routing/{sr}").status_code == 204


def test_required_default_routes_cannot_be_deleted(admin, world, db_session):
    for name in ("Other", CONF):
        rid = db_session.scalar(select(Routing.id).where(Routing.category_id == world["categories"][name].id,
                                                          Routing.unit_id.is_(None)))
        assert admin.delete(f"{API}/admin/routing/{rid}").status_code == 409


def test_list_routing_filter(admin, world):
    page = admin.get(f"{API}/admin/routing?category_id={world['categories']['Hostel and housing'].id}").json()
    assert page["total"] == 3 and page["items"][0]["unit"] is None                          # default listed first


# ---------- routing CSV import ----------

GOOD = ("category,unit,level0_email,level1_email,level2_email\n"
        "Library,,transport@college.edu,registrar@college.edu,\n"
        "Hostel and housing,Hostel A,caretaker_b@college.edu,warden@college.edu,chief_warden@college.edu\n")


def test_template_downloads(admin):
    r = admin.get(f"{API}/admin/routing/template")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.startswith("category,unit,level0_email,level1_email,level2_email")
    assert admin.get(f"{API}/admin/users/template").text.startswith("name,email,role,department,hostel,room")


def test_routing_import_preview_changes_nothing(admin, world, db_session):
    r = admin.post(f"{API}/admin/routing/import", files=csv_file(GOOD)).json()
    assert r["dry_run"] is True and r["created"] == 0 and r["updated"] == 2 and r["errors"] == 0
    lib = db_session.scalar(select(Routing).where(Routing.category_id == world["categories"]["Library"].id))
    db_session.refresh(lib)
    assert lib.level0_user_id == world["users"]["librarian"].id                             # unchanged
    assert db_session.scalars(select(AuditLog)).all() == []


def test_routing_import_apply_reports_bad_rows_but_saves_good_ones(admin, world, db_session):
    bad = GOOD + ("Nonsense,,warden@college.edu,,\n"
                  "Library,Nowhere,warden@college.edu,,\n"
                  "Transport,,nobody@college.edu,,\n"
                  "Transport,,ravi@college.edu,,\n")
    r = admin.post(f"{API}/admin/routing/import?dry_run=false", files=csv_file(bad)).json()
    assert (r["updated"], r["errors"]) == (2, 4)
    errs = {x["row"]: x["message"] for x in r["rows"] if x["action"] == "error"}
    assert "Unknown category" in errs[4] and "Unknown campus location" in errs[5]
    assert "No user with email" in errs[6] and "only staff or officers" in errs[7]
    lib = db_session.scalar(select(Routing).where(Routing.category_id == world["categories"]["Library"].id))
    db_session.refresh(lib)
    assert lib.level0_user_id == world["users"]["transport"].id
    assert db_session.scalars(select(AuditLog)).one().action == "import"


def test_routing_import_creates_new_rows(admin, world, db_session):
    admin.post(f"{API}/admin/units", json={"name": "Hostel C", "type": "hostel"})
    text = "category,unit,level0_email,level1_email,level2_email\nHostel and housing,Hostel C,caretaker_a@college.edu,warden@college.edu,\n"
    r = admin.post(f"{API}/admin/routing/import?dry_run=false", files=csv_file(text)).json()
    assert r["created"] == 1
    assert admin.get(f"{API}/admin/routing?category_id={world['categories']['Hostel and housing'].id}").json()["total"] == 4


# Explicit ids: pytest puts the parameter into PYTEST_CURRENT_TEST, and Windows refuses
# environment values longer than 32767 characters (the second case is a 1 MB string).
@pytest.mark.parametrize("content,status", [
    ("category,unit\nLibrary,\n", 422),                                  # missing columns
    ("x" * (1024 * 1024 + 5), 413),                                     # too large
], ids=["missing-columns", "too-large"])
def test_csv_import_rejects_bad_files(admin, content, status):
    assert admin.post(f"{API}/admin/routing/import", files=csv_file(content)).status_code == status


def test_csv_import_rejects_non_utf8(admin):
    files = {"file": ("a.csv", io.BytesIO(b"category,unit\n\xff\xfe\x00bad"), "text/csv")}
    assert admin.post(f"{API}/admin/routing/import", files=files).status_code == 422


# ---------- users ----------

def test_user_crud_filters_and_validation(admin, world):
    r = admin.post(f"{API}/admin/users", json={"name": "New Clerk", "email": "Clerk1@college.edu", "role": "staff"})
    assert r.status_code == 201 and r.json()["email"] == "clerk1@college.edu"
    assert admin.post(f"{API}/admin/users", json={"name": "X", "email": "clerk1@college.edu"}).status_code == 409
    assert admin.post(f"{API}/admin/users", json={"name": "X", "email": "x@gmail.com"}).status_code == 422
    assert admin.post(f"{API}/admin/users", json={"name": "X", "email": "x@evilcollege.edu"}).status_code == 422
    assert admin.post(f"{API}/admin/users", json={"name": "X", "email": "x@college.edu", "role": "boss"}).status_code == 422
    assert admin.get(f"{API}/admin/users?role=officer").json()["total"] == 2
    assert admin.get(f"{API}/admin/users?q=KUMAR").json()["items"][0]["email"] == "ravi@college.edu"
    assert admin.get(f"{API}/admin/users?q=%25").json()["total"] == 0                       # '%' is not a wildcard
    assert admin.get(f"{API}/admin/users?active=false").json()["total"] == 0


def test_changing_users_and_the_safety_rules(admin, world, client):
    ravi = uid(world, "ravi")
    assert admin.patch(f"{API}/admin/users/{ravi}", json={"room": "A-102", "hostel": "Hostel B"}).json()["room"] == "A-102"
    me = uid(world, "admin")
    assert admin.patch(f"{API}/admin/users/{me}", json={"active": False}).status_code == 409   # not yourself
    assert admin.patch(f"{API}/admin/users/{me}", json={"role": "student"}).status_code == 409
    warden = uid(world, "warden")
    r = admin.patch(f"{API}/admin/users/{warden}", json={"active": False})
    assert r.status_code == 200 and r.json()["in_routes"] >= 3 and "routing row" in r.json()["warnings"][0]
    logout(client)
    assert client.post(f"{API}/auth/dev-login", json={"email": "warden@college.edu"}).status_code == 404


def test_deactivated_staff_are_skipped_in_routing(admin, world, client):
    admin.patch(f"{API}/admin/users/{uid(world, 'caretaker_a')}", json={"active": False})
    logout(client); login_as(client, "ravi")
    assert new_issue(client, world).json()["assignee"]["name"] == "Warden"


def test_users_import(admin, world, db_session):
    text = ("name,email,role,department,hostel,room\n"
            "Asha Nair,asha@college.edu,student,ECE,Hostel B,B-210\n"
            "Ravi K,ravi@college.edu,student,CSE,Hostel A,A-999\n"
            "Bad Mail,bad@gmail.com,student,,,\n"
            "Wrong Role,wr@college.edu,wizard,,,\n"
            "Me,admin@college.edu,student,,,\n"
            ",noname@college.edu,student,,,\n")
    preview = admin.post(f"{API}/admin/users/import", files=csv_file(text)).json()
    assert (preview["created"], preview["updated"], preview["errors"]) == (1, 1, 4)
    assert db_session.scalar(select(User).where(User.email == "asha@college.edu")) is None   # preview saved nothing
    done = admin.post(f"{API}/admin/users/import?dry_run=false", files=csv_file(text)).json()
    assert (done["created"], done["updated"], done["errors"]) == (1, 1, 4)
    assert db_session.scalar(select(User).where(User.email == "asha@college.edu")).room == "B-210"
    db_session.refresh(world["users"]["ravi"])
    assert world["users"]["ravi"].room == "A-999" and world["users"]["ravi"].active is True
    assert world["users"]["admin"].role == "admin"                                          # own role untouched
    msgs = " ".join(r["message"] for r in done["rows"] if r["action"] == "error")
    assert "@college.edu" in msgs and "Unknown role" in msgs and "yourself" in msgs and "Name is required" in msgs


# ---------- audit ----------

def test_audit_log_lists_who_did_what(admin, world):
    admin.post(f"{API}/admin/units", json={"name": "Hostel C", "type": "hostel"})
    admin.patch(f"{API}/admin/users/{uid(world, 'ravi')}", json={"room": "A-5"})
    page = admin.get(f"{API}/admin/audit").json()
    assert page["total"] == 2 and page["items"][0]["actor"] == "admin@college.edu"
    assert {i["entity"] for i in page["items"]} == {"unit", "user"}
    assert admin.get(f"{API}/admin/audit?entity=unit").json()["total"] == 1


# ---------- stats, issues, health ----------

def _tickets(client, world):
    logout(client); login_as(client, "ravi")
    a = new_issue(client, world).json()["id"]
    new_issue(client, world, category="Library", unit=None)
    logout(client); login_as(client, "priya")
    c = new_issue(client, world, category=CONF, unit=None).json()["id"]
    logout(client); login_as(client, "admin")
    return a, c


def test_stats_count_everything_including_confidential(admin, world, client, db_session):
    _tickets(client, world)
    s = admin.get(f"{API}/admin/stats").json()
    assert s["tickets"]["total"] == 3 and s["tickets"]["open"] == 3 and s["tickets"]["by_status"]["ASSIGNED"] == 3
    cats = {c["category"]: c for c in s["by_category"]}
    assert cats[CONF]["confidential"] is True and cats[CONF]["total"] == 1
    assert cats["Library"]["open"] == 1 and s["feedback"] == {"count": 0, "average": None}
    assert s["emails_waiting"] > 0


def test_all_issues_never_lists_confidential(admin, world, client, db_session):
    a, c = _tickets(client, world)
    page = admin.get(f"{API}/admin/issues").json()
    assert page["total"] == 2 and all(not i["confidential"] for i in page["items"])
    assert admin.get(f"{API}/issues/{c}").status_code == 404                                # nor open it
    assert admin.get(f"{API}/admin/issues?q=grv-2026").json()["total"] == 2
    assert admin.get(f"{API}/admin/issues?q=%25").json()["total"] == 0
    lib = str(world["categories"]["Library"].id)
    assert admin.get(f"{API}/admin/issues?category_id={lib}").json()["total"] == 1
    assert admin.get(f"{API}/admin/issues?status=CLOSED").json()["total"] == 0
    assert admin.get(f"{API}/admin/issues?status=BOGUS").status_code == 422
    from datetime import datetime, timedelta, timezone
    db_session.get(Ticket, __import__("uuid").UUID(a)).due_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()
    over = admin.get(f"{API}/admin/issues?overdue=true").json()
    assert over["total"] == 1 and over["items"][0]["id"] == a and over["items"][0]["reporter_name"] == "Ravi Kumar"


def test_admin_can_escalate_an_overdue_normal_ticket(admin, world, client):
    a, _ = _tickets(client, world)
    assert admin.post(f"{API}/issues/{a}/escalate", json={"reason": "Overdue"}).status_code == 200


def test_health_before_and_after_the_worker_runs(admin, world, client, db_session, settings, tmp_path):
    from grievance_app.services import scheduler
    settings.upload_dir = str(tmp_path / "up")
    h = admin.get(f"{API}/admin/health").json()
    assert h["worker"]["status"] == "never" and h["email"]["configured"] is False
    assert h["checks"]["uploads_dir_writable"] is True and h["checks"]["clamav_enabled"] is False
    _tickets(client, world)
    scheduler.run_once(db_session)
    h = admin.get(f"{API}/admin/health").json()
    assert h["worker"]["status"] == "ok" and h["worker"]["last_run"]["escalated"] == 0 and h["worker"]["minutes_ago"] < 1
    assert h["email"]["gave_up"] > 0 and h["email"]["recent_failures"][0]["error"] == "Email is not configured"


def test_health_reports_stale_worker(admin, world, db_session):
    from datetime import datetime, timedelta, timezone
    from grievance_app.services.state import set_state
    set_state(db_session, "scheduler_heartbeat", (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat())
    assert admin.get(f"{API}/admin/health").json()["worker"]["status"] == "stale"
