# routers/auth.py

import os
import re
import secrets

from fastapi import APIRouter, HTTPException, Query
from googleapiclient.discovery import build

from services.gmail_auth import (
    build_auth_url,
    exchange_code_for_tokens,
    get_valid_credentials,
)


router = APIRouter(
    prefix="/auth",
    tags=["Google OAuth & Gmail Watch"],
)


DEFAULT_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8000/auth/google/callback",
)

GCP_TOPIC_NAME = os.getenv("GCP_PUBSUB_TOPIC")


# Temporary OAuth state store.
# The state is deliberately NOT the user's email.
_OAUTH_STATES = {}


def _safe_user_id(user_id: str) -> str:
    """
    Sanitize user_id before using it in a filesystem path.
    """
    return re.sub(r"[^a-zA-Z0-9._@-]", "_", user_id)


@router.get(
    "/google/login",
    summary="Generate Google OAuth Login Link",
)
def google_login(
    user_email: str = Query(
        ...,
        description="The user's email address (e.g. user@gmail.com)",
    ),
    redirect_uri: str = Query(
        DEFAULT_REDIRECT_URI,
        description="OAuth Redirect URI registered in Google Console",
    ),
):
    """
    Step 1: Generate the Google Login URL.

    The OAuth state is random and stored temporarily so it can
    be validated when Google redirects back to the callback.
    """
    try:
        auth_url, state = build_auth_url(
            user_id=user_email,
            redirect_uri=redirect_uri,
        )

        _OAUTH_STATES[state] = user_email

        return {
            "status": "success",
            "user_email": user_email,
            "auth_url": auth_url,
            "instructions": (
                "Copy and open the auth_url in your browser "
                "to authorize Gmail access."
            ),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate login URL: {str(exc)}",
        )


@router.get(
    "/google/callback",
    summary="Google OAuth Callback Handler",
)
def google_callback(
    code: str = Query(
        ...,
        description="Authorization code returned by Google",
    ),
    state: str = Query(
        ...,
        description="Random OAuth state returned by Google",
    ),
    redirect_uri: str = Query(
        DEFAULT_REDIRECT_URI,
        description="Matching OAuth Redirect URI",
    ),
):
    """
    Step 2: Handle the redirect back from Google.

    1. Validate the OAuth state.
    2. Exchange the authorization code for credentials.
    3. Save credentials to tokens/{user_email}.json.
    """
    user_email = _OAUTH_STATES.pop(state, None)

    if not user_email:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state.",
        )

    try:
        creds = exchange_code_for_tokens(
            code=code,
            redirect_uri=redirect_uri,
            user_id=user_email,
        )

        return {
            "message": f"Successfully authenticated {user_email}!",
            "user_email": user_email,
            "credentials_saved": True,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to exchange token: {str(exc)}",
        )


@router.post(
    "/gmail/watch",
    summary="Register or Renew Gmail Watch Subscription",
)
def register_watch(
    user_email: str = Query(
        ...,
        description="The authenticated user's email address",
    ),
    topic_name: str = Query(
        None,
        description="Format: projects/PROJECT_ID/topics/TOPIC_NAME",
    ),
):
    """
    Register or renew a Gmail Pub/Sub watch subscription.

    Gmail watch subscriptions expire after 7 days and must be renewed.
    """
    topic_name = topic_name or GCP_TOPIC_NAME

    if not topic_name:
        raise HTTPException(
            status_code=400,
            detail="GCP Pub/Sub topic is not configured.",
        )

    if not topic_name.startswith("projects/") or "/topics/" not in topic_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid topic format. Must be: "
                "projects/PROJECT_ID/topics/TOPIC_NAME"
            ),
        )

    try:
        creds = get_valid_credentials(
            user_id=user_email
        )

        gmail = build(
            "gmail",
            "v1",
            credentials=creds,
        )

        request_body = {
            "topicName": topic_name,
            "labelIds": ["INBOX"],
        }

        response = (
            gmail.users()
            .watch(
                userId="me",
                body=request_body,
            )
            .execute()
        )

        history_id = response.get("historyId")

        # The PDF requires the historyId returned by Gmail
        # to be saved for subsequent history processing.
        from services.history_state import set_last_history_id

        if history_id:
            set_last_history_id(
                user_email,
                history_id,
            )

        return {
            "status": "success",
            "user_email": user_email,
            "topic_name": topic_name,
            "history_id": history_id,
            "expiration_ms": response.get("expiration"),
            "note": (
                "Gmail watch subscriptions expire every 7 days "
                "and must be renewed."
            ),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to register watch: {str(exc)}",
        )


@router.post(
    "/gmail/stop",
    summary="Stop Gmail Watch Subscription",
)
def stop_watch(
    user_email: str = Query(
        ...,
        description="The authenticated user's email address to stop watching",
    ),
    remove_token: bool = Query(
        True,
        description="Whether to also delete stored credentials from disk",
    ),
):
    """
    Stop real-time push notifications for the specified Gmail inbox.
    """
    try:
        creds = get_valid_credentials(
            user_id=user_email
        )

        gmail = build(
            "gmail",
            "v1",
            credentials=creds,
        )

        gmail.users().stop(
            userId="me"
        ).execute()

        token_removed = False

        if remove_token:
            safe_user_id = _safe_user_id(user_email)

            token_path = os.path.join(
                "tokens",
                f"{safe_user_id}.json",
            )

            if os.path.exists(token_path):
                os.remove(token_path)
                token_removed = True

        return {
            "status": "success",
            "message": (
                f"Successfully stopped watching Gmail inbox "
                f"for {user_email}."
            ),
            "user_email": user_email,
            "watch_stopped": True,
            "token_removed": token_removed,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop watch: {str(exc)}",
        )


@router.post(
    "/gmail/backfill",
    summary="Trigger Full Historical Email Backfill",
)
def trigger_backfill(
    user_email: str = Query(
        ...,
        description="The authenticated user's email address",
    ),
    limit: int = Query(
        10,
        description="Max number of emails to backfill",
    ),
    clear_dedup: bool = Query(
        False,
        description="Whether to clear dedup cache to reprocess emails",
    ),
):
    """
    Trigger a full historical mailbox scan.

    The backfill worker is responsible for filtering Gmail
    messages to IITJ senders.
    """
    try:
        from jobs.backfillworker import start_backfill
        from services.dedup import clear_dedup_store

        if clear_dedup:
            clear_dedup_store()

        batches_queued = start_backfill(
            user_id=user_email,
            limit=limit,
        )

        return {
            "status": "success",
            "message": (
                f"Historical backfill initiated for {user_email}."
            ),
            "user_email": user_email,
            "batches_queued": batches_queued,
            "emails_limit": limit,
            "note": (
                "Celery workers are processing these batches "
                "in the background."
            ),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start backfill: {str(exc)}",
        )