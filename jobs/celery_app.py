import os

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

celery_app = Celery(
    "ask_ai_email_pipeline",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    include=["jobs.email_tasks", "jobs.retention_tasks", "jobs.watch_tasks"],
)

celery_app.conf.update(
    task_acks_late=True,  # don't ack until the task actually finishes
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # avoid one worker hoarding many slow OCR tasks
    broker_pool_limit=1,  # minimal connection pooling for cloud Redis
    redis_max_connections=5,  # cap connection pool
    worker_send_task_events=False,  # disable event monitoring overhead
    broker_connection_retry_on_startup=True,

    # Maintenance jobs. Both are inert until explicitly armed through .env:
    # retention does nothing while RETENTION_ENABLED is false, and watch renewal
    # only touches mailboxes listed in GMAIL_ACCOUNT_IDS.
    beat_schedule={
        "renew-gmail-watches": {
            # Watches expire after 7 days, so renew every 2 days with margin.
            "task": "jobs.watch_tasks.renew_all_watches_task",
            "schedule": crontab(hour=2, minute=0, day_of_week="*/2"),
        },
        "purge-unused-email-chunks": {
            "task": "jobs.retention_tasks.purge_unused_email_chunks_task",
            "schedule": crontab(hour=3, minute=30),
        },
    },
)
