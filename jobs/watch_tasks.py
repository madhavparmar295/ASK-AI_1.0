"""
Keep real-time ingestion alive for every configured mailbox.

Gmail Pub/Sub watches expire after 7 days. Once one expires, new mail for that
mailbox stops arriving silently, which is easy to miss when 30 mailboxes are
involved. This task renews them all on a schedule.

Run manually:

    python -m jobs.watch_tasks
"""

import argparse

from jobs.celery_app import celery_app
from services.gmail_auth import configured_accounts, register_watch


def renew_all_watches() -> dict:
    """Renew every configured mailbox's watch, isolating per-mailbox failures."""
    accounts = configured_accounts()
    if not accounts:
        print("[Watch] No mailboxes configured (GMAIL_ACCOUNT_IDS is empty).")
        return {"accounts": 0, "renewed": 0, "results": {}}

    results: dict[str, str] = {}
    for account in accounts:
        try:
            outcome = register_watch(account)
            results[account] = f"ok (history {outcome.get('history_id')})"
        except Exception as exc:
            # One broken token must not stop the other mailboxes being renewed.
            results[account] = f"error: {exc}"
            print(f"[Watch] Renewal failed for {account}: {exc}")

    renewed = sum(1 for status in results.values() if status.startswith("ok"))
    print(f"[Watch] Renewed {renewed}/{len(accounts)} mailboxes.")
    return {"accounts": len(accounts), "renewed": renewed, "results": results}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def renew_all_watches_task(self):
    """Scheduled entry point."""
    try:
        return renew_all_watches()
    except Exception as exc:
        print(f"[Watch] Renewal run failed: {exc}")
        raise self.retry(exc=exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Renew Gmail watches for all mailboxes.")
    parser.parse_args()
    print(renew_all_watches())


if __name__ == "__main__":
    main()
