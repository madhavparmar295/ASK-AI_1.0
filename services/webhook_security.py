import os

from google.auth.transport import requests
from google.oauth2 import id_token


PUBSUB_OIDC_AUDIENCE = os.getenv("PUBSUB_OIDC_AUDIENCE")
PUBSUB_OIDC_SERVICE_ACCOUNT = os.getenv("PUBSUB_OIDC_SERVICE_ACCOUNT")


def verify_pubsub_oidc_token(authorization: str | None) -> dict:
    """
    Verify the OIDC JWT sent by Google Pub/Sub.

    The token must:
    - be sent as: Authorization: Bearer <JWT>
    - have the expected audience
    - be issued by Google
    - have a verified email
    - come from the configured Pub/Sub push service account
    """

    if not authorization:
        raise ValueError("Missing Authorization header")

    parts = authorization.split()

    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("Invalid Authorization header")

    token = parts[1]

    audience_cfg = os.getenv("PUBSUB_OIDC_AUDIENCE") or PUBSUB_OIDC_AUDIENCE
    if not audience_cfg:
        raise RuntimeError(
            "PUBSUB_OIDC_AUDIENCE is not configured"
        )

    service_account_cfg = os.getenv("PUBSUB_OIDC_SERVICE_ACCOUNT") or PUBSUB_OIDC_SERVICE_ACCOUNT
    if not service_account_cfg:
        raise RuntimeError(
            "PUBSUB_OIDC_SERVICE_ACCOUNT is not configured"
        )

    # Verify Google's signed OIDC token
    claims = id_token.verify_oauth2_token(
        token,
        requests.Request(),
    )

    # Check audience: allow base URL and /webhook/gmail endpoint URL
    base_aud = audience_cfg.rstrip("/")
    allowed_audiences = {
        base_aud,
        f"{base_aud}/webhook/gmail",
        base_aud[:-len("/webhook/gmail")] if base_aud.endswith("/webhook/gmail") else base_aud,
    }
    token_aud = claims.get("aud")
    if token_aud not in allowed_audiences:
        raise ValueError(
            f"Token has wrong audience {token_aud}, expected one of {list(allowed_audiences)}"
        )

    # Verify token issuer.
    issuer = claims.get("iss")

    if issuer not in (
        "https://accounts.google.com",
        "accounts.google.com",
    ):
        raise ValueError("Invalid OIDC token issuer")

    # Verify that Google's email claim is verified.
    if claims.get("email_verified") is not True:
        raise ValueError("OIDC email is not verified")

    # Verify that the token was issued for the exact
    # Pub/Sub push service account configured in GCP.
    token_email = claims.get("email")

    if token_email != service_account_cfg:
        raise ValueError(
            "Unexpected Pub/Sub service account"
        )

    return claims