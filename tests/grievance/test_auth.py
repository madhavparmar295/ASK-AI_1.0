import pytest

from grievance_app.auth import google
from grievance_app.auth.google import AuthError
from grievance_app.models import User
from grievance_app.security import ratelimit
from tests.grievance.conftest import login_as

API = "/api/grievance"


# ---------- /me and sessions ----------

def test_me_requires_login(client):
    assert client.get(f"{API}/me").status_code == 401


def test_dev_login_and_me(client):
    data = login_as(client, "ravi")
    assert data["role"] == "student" and data["is_head"] is False
    me = client.get(f"{API}/me").json()
    assert me["email"] == "ravi@college.edu"
    assert "csrf_token" in me


def test_session_cookie_flags(client):
    r = client.post(f"{API}/auth/dev-login", json={"email": "ravi@college.edu"})
    cookies = r.headers.get_list("set-cookie")
    session = [c for c in cookies if c.startswith("grievance_session=")][0].lower()
    csrf = [c for c in cookies if c.startswith("grievance_csrf=")][0].lower()
    assert "httponly" in session and "samesite=lax" in session
    assert "httponly" not in csrf


def test_tampered_cookie_rejected(client):
    login_as(client, "ravi")
    client.cookies.set("grievance_session", "garbage")
    assert client.get(f"{API}/me").status_code == 401


def test_head_flag(client):
    assert login_as(client, "warden")["is_head"] is True       # level 1 in routing
    assert login_as(client, "caretaker_a")["is_head"] is False  # level 0 only


def test_logout_clears_session(client):
    login_as(client, "ravi")
    assert client.post(f"{API}/auth/logout").status_code == 200
    client.cookies.clear()
    assert client.get(f"{API}/me").status_code == 401


def test_deactivated_user_cannot_login_or_use_session(client, db_session):
    login_as(client, "ravi")
    user = db_session.query(User).filter_by(email="ravi@college.edu").one()
    user.active = False
    db_session.commit()
    assert client.get(f"{API}/me").status_code == 401          # existing session dies
    client.cookies.clear()
    r = client.post(f"{API}/auth/dev-login", json={"email": "ravi@college.edu"})
    assert r.status_code == 404


# ---------- CSRF ----------

def test_csrf_required_on_post(client):
    r = client.post(f"{API}/auth/dev-login", json={"email": "ravi@college.edu"})
    token = r.json()["csrf_token"]
    assert client.post(f"{API}/auth/logout").status_code == 403                   # no header
    assert client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": token}).status_code == 200


# ---------- dev login switch ----------

def test_dev_login_disabled(client, settings):
    settings.dev_login_enabled = False
    assert client.post(f"{API}/auth/dev-login", json={"email": "ravi@college.edu"}).status_code == 404
    assert client.get(f"{API}/auth/dev-users").status_code == 404


def test_dev_users_list(client):
    r = client.get(f"{API}/auth/dev-users")
    assert r.status_code == 200 and any(u["email"] == "admin@college.edu" for u in r.json())


def test_login_rate_limit(client, settings):
    settings.login_rate_limit_per_minute = 3
    codes = [client.post(f"{API}/auth/dev-login", json={"email": "ravi@college.edu"}).status_code
             for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    ratelimit.reset()


# ---------- Google credential verification ----------

def _patch_google(monkeypatch, payload=None, error=False):
    def fake_verify(credential, request, audience):
        if error:
            raise ValueError("bad token")
        assert audience == "test-client-id"
        return payload
    monkeypatch.setattr(google.id_token, "verify_oauth2_token", fake_verify)


GOOD = {"email": "Ravi@college.edu", "email_verified": True, "name": "Ravi", "hd": "college.edu"}


def test_google_verify_ok(monkeypatch, settings):
    _patch_google(monkeypatch, GOOD)
    assert google.verify_google_credential("x") == {"email": "ravi@college.edu", "name": "Ravi"}


@pytest.mark.parametrize("payload,status", [
    ({**GOOD, "email_verified": False}, 403),
    ({**GOOD, "email": "someone@gmail.com", "hd": None}, 403),
    ({**GOOD, "email": "x@evilcollege.edu"}, 403),     # suffix trick
    ({**GOOD, "hd": "other.edu"}, 403),
    ({k: v for k, v in GOOD.items() if k != "hd"}, 403),
])
def test_google_verify_rejects(monkeypatch, settings, payload, status):
    _patch_google(monkeypatch, payload)
    with pytest.raises(AuthError) as e:
        google.verify_google_credential("x")
    assert e.value.status == status


def test_google_verify_invalid_token(monkeypatch, settings):
    _patch_google(monkeypatch, error=True)
    with pytest.raises(AuthError) as e:
        google.verify_google_credential("x")
    assert e.value.status == 401


def test_google_verify_not_configured(settings):
    settings.google_client_id = ""
    with pytest.raises(AuthError) as e:
        google.verify_google_credential("x")
    assert e.value.status == 503


# ---------- Google login route ----------

def _route_patch(monkeypatch, email, name="Someone"):
    monkeypatch.setattr(google, "verify_google_credential",
                        lambda credential: {"email": email, "name": name})


def test_google_login_registered_user(client, monkeypatch):
    _route_patch(monkeypatch, "ravi@college.edu")
    r = client.post(f"{API}/auth/google", json={"credential": "x"})
    assert r.status_code == 200 and r.json()["role"] == "student"
    assert client.get(f"{API}/me").status_code == 200


def test_google_login_unknown_email_rejected(client, monkeypatch):
    _route_patch(monkeypatch, "stranger@college.edu")
    assert client.post(f"{API}/auth/google", json={"credential": "x"}).status_code == 403


def test_google_login_unknown_email_as_student(client, monkeypatch, settings):
    settings.unknown_email_policy = "student"
    _route_patch(monkeypatch, "stranger@college.edu", "Stranger")
    r = client.post(f"{API}/auth/google", json={"credential": "x"})
    assert r.status_code == 200 and r.json()["role"] == "student"


def test_google_login_deactivated(client, monkeypatch, db_session):
    db_session.query(User).filter_by(email="ravi@college.edu").one().active = False
    db_session.commit()
    _route_patch(monkeypatch, "ravi@college.edu")
    assert client.post(f"{API}/auth/google", json={"credential": "x"}).status_code == 403


def test_google_login_bad_credential(client, monkeypatch):
    def boom(credential):
        raise AuthError("Invalid Google credential")
    monkeypatch.setattr(google, "verify_google_credential", boom)
    assert client.post(f"{API}/auth/google", json={"credential": "x"}).status_code == 401


def test_health(client):
    assert client.get(f"{API}/health").json() == {"status": "ok"}


def test_health_answers_get_and_head(client):
    assert client.get(f"{API}/health").json() == {"status": "ok"}
    assert client.head(f"{API}/health").status_code == 200
