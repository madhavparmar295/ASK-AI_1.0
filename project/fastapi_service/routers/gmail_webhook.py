import base64
import json
import os
from fastapi import APIRouter, Request, HTTPException, Query
from googleapiclient.discovery import build

from services.webhook_security import verify_webhook_signature
from services.gmail_auth import get_valid_credentials
from jobs.email_tasks import process_new_email_task

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _get_fallback_user_id() -> str | None:
    token_dir = "tokens"
    if os.path.exists(token_dir):
        files = [f for f in os.listdir(token_dir) if f.endswith(".json")]
        if files:
            return files[0].replace(".json", "")
    return None


@router.post("/gmail")
async def gmail_webhook(request: Request, secret: str = Query(None)):
    webhook_secret = os.getenv("GMAIL_WEBHOOK_SECRET")
    # Validate webhook secret token if configured
    if webhook_secret and secret != webhook_secret:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid webhook secret token")

    payload = await request.json()
    message_data = payload.get("message", {})
    raw_data = message_data.get("data", "")

    user_id = None
    message_id = None

    if raw_data:
        try:
            # Fix base64 URL-safe padding
            padded_data = raw_data + "=" * (-len(raw_data) % 4)
            decoded_bytes = base64.urlsafe_b64decode(padded_data)
            decoded_json = json.loads(decoded_bytes.decode("utf-8"))

            if isinstance(decoded_json, dict):
                user_id = decoded_json.get("emailAddress")
        except Exception as err:
            print(f"Pub/Sub payload decoding notice: {err}")

    # Fallback to Pub/Sub attributes
    if not user_id:
        user_id = message_data.get("attributes", {}).get("emailAddress")

    # Fallback to stored token directory
    if not user_id:
        user_id = _get_fallback_user_id()

    if not user_id:
        raise HTTPException(status_code=400, detail="Could not determine user_id for Gmail notification")

    # Fetch latest Gmail message_id for this user
    try:
        creds = get_valid_credentials(user_id)
        gmail = build("gmail", "v1", credentials=creds)
        list_res = gmail.users().messages().list(userId="me", maxResults=1).execute()
        messages = list_res.get("messages", [])
        if messages:
            message_id = messages[0]["id"]
    except Exception as exc:
        print(f"Failed to fetch latest message for {user_id}: {exc}")

    if not message_id:
        message_id = raw_data if (raw_data and len(raw_data) < 50) else "latest"

    # Hand off to Celery queue
    process_new_email_task.delay(user_id=user_id, message_id=message_id)

    return {"status": "queued", "user_id": user_id, "message_id": message_id}

