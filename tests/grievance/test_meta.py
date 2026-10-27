from tests.grievance.conftest import login_as, logout, new_issue

API = "/api/grievance"


def test_form_options_lists_active_categories_and_units(client, world):
    assert client.get(f"{API}/meta/form-options").status_code == 401
    login_as(client, "ravi")
    d = client.get(f"{API}/meta/form-options").json()
    assert len(d["categories"]) == 12 and len(d["units"]) == 8
    conf = [c for c in d["categories"] if c["confidential"]]
    assert [c["name"] for c in conf] == ["Harassment, ragging, discrimination, safety"]
    assert {c["unit_type"] for c in d["categories"]} >= {"hostel", "department", "campus"}


def test_inactive_items_are_hidden(client, world, db_session):
    world["categories"]["Library"].active = False
    world["units"]["Hostel B"].active = False
    db_session.commit()
    login_as(client, "ravi")
    d = client.get(f"{API}/meta/form-options").json()
    assert "Library" not in [c["name"] for c in d["categories"]]
    assert "Hostel B" not in [u["name"] for u in d["units"]]


def test_reassign_options(client, world):
    login_as(client, "ravi")
    tid = new_issue(client, world).json()["id"]
    assert client.get(f"{API}/issues/{tid}/reassign-options").status_code == 403         # reporter
    logout(client); login_as(client, "caretaker_a")
    assert client.get(f"{API}/issues/{tid}/reassign-options").status_code == 403         # level 0 cannot reassign
    logout(client); login_as(client, "warden")
    names = [p["name"] for p in client.get(f"{API}/issues/{tid}/reassign-options").json()]
    assert "Caretaker Hostel B" in names and "Caretaker Hostel A" not in names             # current assignee excluded
    assert "Ravi Kumar" not in names and "Admin Office" not in names                       # no students, no admins
    logout(client); login_as(client, "priya")
    assert client.get(f"{API}/issues/{tid}/reassign-options").status_code == 404           # cannot see the ticket


def test_confidential_reassign_options_are_officers_only(client, world):
    login_as(client, "priya")
    tid = new_issue(client, world, category="Harassment, ragging, discrimination, safety", unit=None).json()["id"]
    logout(client); login_as(client, "officer1")
    opts = client.get(f"{API}/issues/{tid}/reassign-options").json()
    assert [p["name"] for p in opts] == ["Designated Officer 2"]
    logout(client); login_as(client, "admin")
    assert client.get(f"{API}/issues/{tid}/reassign-options").status_code == 404
