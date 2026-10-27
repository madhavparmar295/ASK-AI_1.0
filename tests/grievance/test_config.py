import pytest

from grievance_app.config import Settings

SAFE = dict(env="production", dev_login_enabled=False, cookie_secure=True,
            secret_key="x" * 40, google_client_id="abc")


def test_safe_production_config_is_accepted():
    Settings(**SAFE).validate_for_runtime()


@pytest.mark.parametrize("override", [
    {"dev_login_enabled": True},
    {"secret_key": "change-me"},
    {"secret_key": "short"},
    {"cookie_secure": False},
    {"google_client_id": ""},
])
def test_unsafe_production_config_refuses_to_start(override):
    with pytest.raises(RuntimeError):
        Settings(**{**SAFE, **override}).validate_for_runtime()


def test_bad_unknown_email_policy_refused():
    with pytest.raises(RuntimeError):
        Settings(unknown_email_policy="maybe").validate_for_runtime()


def test_development_config_allows_defaults():
    Settings(env="development").validate_for_runtime()
