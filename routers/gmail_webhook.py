import base64
import json

from fastapi import APIRouter, Request, HTTPException

from jobs.email_tasks import process_history_task
from services.webhook_security import verify_pubsub_oidc_token


router = APIRouter(
    prefix="/webhook",
    tags=["gmail-webhook"],
)


@router.post("/gmail")
async def gmail_webhook(request: Request):
    
    # 1. Verify Google Pub/Sub OIDC authentication
    authorization = request.headers.get("Authorization")

    try:
        claims = verify_pubsub_oidc_token(authorization)

        print(
            "[Gmail Webhook] OIDC verified: "
            f"{claims.get('email')}"
        )

    except Exception as exc:
        print(
            f"[Gmail Webhook] OIDC verification failed: {exc}"
        )

        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )

    try:
        payload = await request.json()
    except Exception:
        return {
            "status": "ignored",
            "reason": "invalid JSON payload",
        }

    message = payload.get("message", {})
    encoded_data = message.get("data")

    if not encoded_data:
        return {
            "status": "ignored",
            "reason": "missing message data",
        }

    try:
        decoded_data = base64.b64decode(
            encoded_data
        ).decode("utf-8")

        notification = json.loads(decoded_data)

    except Exception:
        return {
            "status": "ignored",
            "reason": "invalid message data",
        }

    email_address = notification.get("emailAddress")
    history_id = notification.get("historyId")

    if not email_address or not history_id:
        return {
            "status": "ignored",
            "reason": "missing emailAddress or historyId",
        }


    print(
        f"[Gmail Webhook] email={email_address}, "
        f"historyId={history_id}"
    )

    process_history_task.delay(
        user_id=email_address,
        history_id=str(history_id),
    )

    return {
        "status": "queued"
    }