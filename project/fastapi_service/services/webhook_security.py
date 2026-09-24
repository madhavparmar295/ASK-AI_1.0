"""
Verifies that an incoming Pub/Sub push notification genuinely originated
from Google and was not tampered with in transit, before any downstream
processing (fetch, OCR, chunking, LLM calls) is allowed to run.

This is the cheapest possible check in the whole pipeline, so it sits
first in routers/gmail_webhook.py -- reject fast, before spending any
real work on an untrusted request.
"""

import hashlib
import hmac
import os

WEBHOOK_SECRET = os.getenv("GMAIL_WEBHOOK_SECRET")


def verify_webhook_signature(payload: bytes, received_signature: str) -> bool:
    """
    Recompute the HMAC-SHA256 signature over the raw payload using the
    shared secret, and compare it against what Google sent. A mismatch
    means either the payload was altered, or the sender never had the
    secret in the first place (i.e. it isn't really Google).
    """
    if not WEBHOOK_SECRET:
        raise RuntimeError("GMAIL_WEBHOOK_SECRET is not configured")

    expected_signature = hmac.new(
        key=WEBHOOK_SECRET.encode(),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison: prevents an attacker from using response-time
    # differences to guess the correct signature one character at a time.
    return hmac.compare_digest(expected_signature, received_signature)
