from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from jobs.celery_app import celery_app
from services.gmail_auth import get_valid_credentials

from services.rate_limiter import acquire_token
from services.sender_filter import (
    fetch_from_header,
    is_allowed_sender,
)
from services.history_state import (
    get_last_history_id,
    set_last_history_id,
)

@celery_app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=30,
)
def process_new_email_task(
    self,
    user_id: str,
    message_id: str,
):
    try:
        acquire_token(bucket="gmail_api")

        creds = get_valid_credentials(user_id)

        gmail = build(
            "gmail",
            "v1",
            credentials=creds,
        )

        # Check sender using metadata BEFORE downloading
        # the full email body.
        from_header = fetch_from_header(
            gmail,
            message_id,
        )

        if not is_allowed_sender(from_header):
            print(
                f"[Sender Filter] Rejected message "
                f"{message_id}: {from_header}"
            )
            return

        # Only allowed IITJ messages reach the full-message fetch.
        message = (
            gmail.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="full",
            )
            .execute()
        )

        _index_email(
            message,
            gmail=gmail,
        )

    except HttpError as exc:
        if exc.resp.status == 404:
            print(f"[Email Tasks] Message {message_id} not found (404), skipping.")
            return
        raise self.retry(exc=exc)
    except Exception as exc:
        # Actual processing/API failures are retried.
        # Sender rejection above is NOT retried.
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_backfill_batch_task(
    self,
    user_id: str,
    message_ids: list[str],
):
    creds = get_valid_credentials(user_id)

    gmail = build(
        "gmail",
        "v1",
        credentials=creds,
    )

    for message_id in message_ids:
        try:
            acquire_token(bucket="gmail_api")

            # Check sender metadata BEFORE fetching the full message.
            from_header = fetch_from_header(
                gmail,
                message_id,
            )

            if not is_allowed_sender(from_header):
                print(
                    f"[Sender Filter] Rejected backfill message "
                    f"{message_id}: {from_header}"
                )
                continue

            message = (
                gmail.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="full",
                )
                .execute()
            )

            _index_email(
                message,
                gmail=gmail,
            )

        except Exception as exc:
            # A failure on one message should not kill the batch.
            print(
                f"Failed to process message {message_id}: {exc}"
            )
            continue

@celery_app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=30,
)
def process_history_task(
    self,
    user_id: str,
    history_id: str,
):
    """
    Process Gmail history changes after a Pub/Sub notification.

    Pub/Sub tells us that Gmail changed. Gmail history tells us
    which messages actually changed.
    """

    try:
        acquire_token(bucket="gmail_api")

        creds = get_valid_credentials(user_id)

        gmail = build(
            "gmail",
            "v1",
            credentials=creds,
        )

        start_history_id = get_last_history_id(user_id)

        if not start_history_id:
            set_last_history_id(
                user_id,
                history_id,
            )
            return

        page_token = None

        while True:
            acquire_token(bucket="gmail_api")

            response = (
                gmail.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded"],
                    pageToken=page_token,
                )
                .execute()
            )

            for history_record in response.get(
                "history",
                [],
            ):
                for message_added in history_record.get(
                    "messagesAdded",
                    [],
                ):
                    message = message_added.get(
                        "message",
                        {},
                    )

                    message_id = message.get("id")

                    if message_id:
                        process_new_email_task.delay(
                            user_id=user_id,
                            message_id=message_id,
                        )

            page_token = response.get(
                "nextPageToken"
            )

            if not page_token:
                break

        set_last_history_id(
            user_id,
            history_id,
        )

    except Exception as exc:
        raise self.retry(exc=exc)


from services.content_dedup import mark_indexed, release
from services.email_processing import extract_from_email
from services.ingest import index_record_to_pinecone

def _index_email(
    message: dict,
    gmail=None,
) -> None:
    """Shared tail end: extract -> store metadata + vectors in Postgres and Pinecone."""
    records = extract_from_email(message, gmail=gmail)
    if not records:
        print(f"[Dedup/Filter] Email {message.get('id')} rejected, processed, or empty. Skipping.")
        return

    for record in records:
        fingerprints = record.pop("_content_fingerprints", [])
        doc_id = record.get("doc_id", "")

        # Email goes straight to Pinecone: the chunk text and every field retrieval
        # needs live in vector metadata, so no PostgreSQL row is written for mail.
        indexed = index_record_to_pinecone(record)
        print(
            f"[Pinecone] Indexed document '{record.get('source')}' "
            f"(doc_id: {doc_id}, indexed: {indexed})."
        )

        for kind, fingerprint in fingerprints:
            if indexed:
                mark_indexed(kind, fingerprint, doc_id)
            else:
                # Nothing reached Pinecone, so drop the claim: the next mailbox that
                # receives this notice can retry it instead of being skipped forever
                # by a claim that never completed.
                release(kind, fingerprint)