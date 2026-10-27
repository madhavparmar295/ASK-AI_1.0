import os

# Settings must be in place before the app is imported. The GRIEVANCE_ prefix keeps these
# out of the chatbot's namespace: the two services share one .env and one process now.
os.environ.update({
    "GRIEVANCE_ENV": "test",
    "GRIEVANCE_DATABASE_URL": "sqlite://",
    "GRIEVANCE_AUTO_CREATE_TABLES": "false",      # the fixtures below build the schema
    "GRIEVANCE_SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
    "GRIEVANCE_ALLOWED_EMAIL_DOMAIN": "college.edu",
    "GRIEVANCE_GOOGLE_CLIENT_ID": "test-client-id",
    "GRIEVANCE_DEV_LOGIN_ENABLED": "true",
    "GRIEVANCE_COOKIE_SECURE": "false",
    "GRIEVANCE_UNKNOWN_EMAIL_POLICY": "reject",
    "GRIEVANCE_REQUIRE_HD": "true",
    "GRIEVANCE_WATCHDOG_ENABLED": "false",
})

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from grievance_app.config import get_settings
from grievance_app.db import Base, get_db, make_engine
from grievance_app.main import create_app
from grievance_app.security import ratelimit
from grievance_app.seed import seed


@pytest.fixture()
def settings():
    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


@pytest.fixture()
def db_session():
    # Default: fast in-memory SQLite. To run the same tests on PostgreSQL:
    #   TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost/dbname pytest
    engine = make_engine(os.environ.get("TEST_DATABASE_URL") or "sqlite://")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as session:
        yield session
        session.rollback()
    Base.metadata.drop_all(engine)
    engine.dispose()                      # free the connections (matters on PostgreSQL)


@pytest.fixture()
def world(db_session):
    """Seeded data: dict with users, categories, units."""
    return seed(db_session)


@pytest.fixture()
def client(db_session, world, settings):
    ratelimit.reset()
    app = create_app()

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c


def login_as(client, key, domain="college.edu"):
    """Dev-login as a seeded user and attach the CSRF header for later requests."""
    r = client.post("/api/grievance/auth/dev-login", json={"email": f"{key}@{domain}"})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r.json()


# ---------- helpers for ticket tests ----------

def logout(client):
    client.post("/api/grievance/auth/logout")
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)


def new_issue(client, world, category="Hostel and housing", unit="Hostel A", **extra):
    """POST /issues with ids taken from the seeded data. Returns the response."""
    body = {"description": "The AC in my room is not working at all",
            "category_id": str(world["categories"][category].id)}
    if unit:
        body["unit_id"] = str(world["units"][unit].id)
    body.update(extra)
    return client.post("/api/grievance/issues", json=body)


@pytest.fixture()
def upload_dir(settings, tmp_path):
    settings.upload_dir = str(tmp_path / "uploads")
    return tmp_path / "uploads"
