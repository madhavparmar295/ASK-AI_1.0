"""Verify a Google sign-in credential (ID token) on the server."""
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from ..config import get_settings


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def verify_google_credential(credential: str) -> dict:
    """Return {"email", "name"} for a valid college Google account, else raise AuthError.

    Checks: signature, expiry, issuer and audience (done by google-auth),
    email_verified, college domain, and (optionally) the Workspace 'hd' claim.
    """
    s = get_settings()
    if not s.google_client_id:
        raise AuthError("Google sign-in is not configured", 503)
    try:
        info = id_token.verify_oauth2_token(credential, google_requests.Request(), s.google_client_id)
    except ValueError:
        raise AuthError("Invalid Google credential")
    if not info.get("email_verified"):
        raise AuthError("Google email is not verified", 403)
    email = str(info.get("email", "")).lower()
    domain = s.allowed_email_domain.lower()
    if not email.endswith("@" + domain):
        raise AuthError("Only college accounts can sign in", 403)
    if s.require_hd and str(info.get("hd", "")).lower() != domain:
        raise AuthError("Only college Workspace accounts can sign in", 403)
    return {"email": email, "name": info.get("name") or email.split("@")[0]}
