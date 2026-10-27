import os
import pytest

# Ensure testing environment variables
os.environ.setdefault("PINECONE_API_KEY", "fake-key-for-ci")
os.environ.setdefault("OPENAI_API_KEY", "sk-fake-key-for-ci")
os.environ.setdefault("GROQ_API_KEY", "gsk-fake-key-for-ci")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_askai.db")

from fastapi.testclient import TestClient
from main import app
from database import engine, Base, SessionLocal
from models.user import User, OTP

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_and_teardown():
    # Recreate tables before each test
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("./test_askai.db"):
        try:
            os.remove("./test_askai.db")
        except Exception:
            pass


def test_user_registration_and_otp_flow():
    test_email = "tester@example.com"
    test_password = "securePassword123"

    # 1. Register new user
    reg_res = client.post(
        "/auth/register",
        json={"email": test_email, "password": test_password},
    )
    assert reg_res.status_code == 201
    assert "verification code" in reg_res.json()["message"].lower()

    # 2. Verify user exists in database but is unverified
    db = SessionLocal()
    user = db.query(User).filter(User.email == test_email).first()
    assert user is not None
    assert user.is_verified is False

    # Check OTP was created in database
    otp = db.query(OTP).filter(OTP.user_id == user.id).first()
    assert otp is not None
    assert len(otp.code) == 6
    assert otp.is_used is False
    db.close()

    # 3. Try to log in before verification -> Expect 403 Forbidden
    login_fail_res = client.post(
        "/auth/login",
        json={"email": test_email, "password": test_password},
    )
    assert login_fail_res.status_code == 403
    assert "Account is not verified" in login_fail_res.json()["detail"]

    # 4. Verify with wrong code -> Expect 400 Bad Request
    verify_bad_res = client.post(
        "/auth/verify-otp",
        json={"email": test_email, "code": "000000"},
    )
    assert verify_bad_res.status_code == 400
    assert "Invalid or expired" in verify_bad_res.json()["detail"]

    # 5. Verify with the actual OTP code -> Expect 200 and access_token
    verify_res = client.post(
        "/auth/verify-otp",
        json={"email": test_email, "code": otp.code},
    )
    assert verify_res.status_code == 200
    data = verify_res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == test_email
    assert data["user"]["is_verified"] is True

    # 6. Now log in normally -> Expect 200 and access_token
    login_success_res = client.post(
        "/auth/login",
        json={"email": test_email, "password": test_password},
    )
    assert login_success_res.status_code == 200
    token = login_success_res.json()["access_token"]

    # 7. Access /auth/me with Bearer token
    me_res = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["email"] == test_email


def test_universal_bypass_code():
    test_email = "bypass@example.com"
    test_password = "passwordBypass99"

    client.post(
        "/auth/register",
        json={"email": test_email, "password": test_password},
    )

    # Use the universal bypass code 339876
    verify_res = client.post(
        "/auth/verify-otp",
        json={"email": test_email, "code": "339876"},
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["user"]["is_verified"] is True
