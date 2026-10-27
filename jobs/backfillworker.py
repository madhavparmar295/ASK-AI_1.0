# jobs/backfillworker.py

from googleapiclient.discovery import build

from jobs.email_tasks import process_backfill_batch_task
from services.gmail_auth import get_valid_credentials
from services.rate_limiter import acquire_token


BATCH_SIZE = 100


def start_backfill(user_id: str, limit: int = 10) -> int:
    """
    Kicks off a historical backfill for IITJ emails only.

    Queues at most `limit` messages for testing.
    Returns the number of batches queued.
    """

    creds = get_valid_credentials(user_id)

    gmail = build(
        "gmail",
        "v1",
        credentials=creds,
    )

    batches_queued = 0
    total_queued = 0
    page_token = None

    while total_queued < limit:
        acquire_token(bucket="gmail_api")

        remaining = limit - total_queued

        response = (
            gmail.users()
            .messages()
            .list(
                userId="me",
                maxResults=min(BATCH_SIZE, remaining),
                pageToken=page_token,
                q="from:iitj.ac.in",
            )
            .execute()
        )

        message_ids = [
            message["id"]
            for message in response.get("messages", [])
        ]

        if message_ids:
            process_backfill_batch_task.delay(
                user_id=user_id,
                message_ids=message_ids,
            )

            batches_queued += 1
            total_queued += len(message_ids)

        page_token = response.get("nextPageToken")

        if not page_token:
            break

    return batches_queued