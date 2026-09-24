from googleapiclient.discovery import build
from jobs.celery_app import celery_app
from services.email_processing import extract_from_email
from services.gmail_auth import get_valid_credentials
from services.ingest import ingest_record
from services.rate_limiter import acquire_token


@celery_app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=30,  # seconds; Celery backs off from here
)
def process_new_email_task(self, user_id: str, message_id: str):
    try:
        acquire_token(bucket="gmail_api")  # Section 4.3: don't exceed quota

        creds = get_valid_credentials(user_id)
        gmail = build("gmail", "v1", credentials=creds)
        message = gmail.users().messages().get(userId="me", id=message_id, format="full").execute()

        _index_email(message, gmail=gmail)

    except Exception as exc:
        # Transient failures (rate limit, network) get retried; the queue
        # is what makes this "without needing manual intervention" true.
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_backfill_batch_task(self, user_id: str, message_ids: list[str]):
    creds = get_valid_credentials(user_id)
    gmail = build("gmail", "v1", credentials=creds)

    for message_id in message_ids:
        try:
            acquire_token(bucket="gmail_api")
            message = gmail.users().messages().get(userId="me", id=message_id, format="full").execute()
            _index_email(message, gmail=gmail)
        except Exception as exc:
            # One bad message in a batch shouldn't kill the whole batch;
            # log and continue rather than retrying the entire batch task.
            print(f"Failed to process message {message_id}: {exc}")
            continue


def _index_email(message: dict, gmail=None) -> None:
    """Shared tail end: extract -> store document metadata + 384-d vector in Postgres."""
    records = extract_from_email(message, gmail=gmail)
    if not records:
        print(f"[Dedup] Email {message.get('id')} already processed or empty. Skipping.")
        return

    for record in records:
        ingest_record(record)
        print(f"[Postgres] Stored document '{record.get('source')}' " f"(doc_id: {record.get('doc_id')}).")
