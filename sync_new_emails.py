"""
Script to synchronize new emails that arrived after the previous backfill.
Checks Gmail for recent IITJ emails, filters out any already recorded in
processed_message_ids.json, and indexes new email bodies and attachments
directly into PostgreSQL and Pinecone.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

load_dotenv(override=True)

from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build

from jobs.email_tasks import _index_email
from services.dedup import is_already_processed
from services.gmail_auth import configured_accounts, get_valid_credentials
from services.rate_limiter import acquire_token
from services.sender_filter import fetch_from_header, is_allowed_sender


def sync_new_emails(user_email: str, query: str = "from:iitj.ac.in", limit: int = 50):
    print("=" * 65)
    print("[*] ASK-AI New Email Sync")
    print("=" * 65)
    print(f"[*] User Account: {user_email}")
    print(f"[*] Search Query: {query}")
    print(f"[*] Max candidate check: {limit}")

    # 1. Authenticate with Gmail
    try:
        creds = get_valid_credentials(user_email)
    except RefreshError:
        print("\n[!] [Google Auth Expired] Your Gmail OAuth token has expired or was revoked.")
        print(f"[*] Please re-authorize by visiting:")
        print(f"    http://localhost:8000/auth/google/login?user_email={user_email}")
        print("    and opening the returned auth_url in your browser to sign in.")
        return
    except Exception as e:
        print(f"\n[!] [Credentials Error] {e}")
        return

    gmail = build("gmail", "v1", credentials=creds)

    print("[*] Fetching message list from Gmail...")
    acquire_token(bucket="gmail_api")
    try:
        response = (
            gmail.users()
            .messages()
            .list(
                userId="me",
                maxResults=limit,
                q=query,
            )
            .execute()
        )
    except Exception as e:
        print(f"[!] Failed to list messages from Gmail: {e}")
        return

    messages = response.get("messages", [])
    if not messages:
        print("[*] No messages found matching the query.")
        return

    print(f"[*] Inspected latest {len(messages)} messages from Gmail.")
    print("-" * 65)

    new_count = 0
    skipped_count = 0

    for idx, msg_meta in enumerate(messages, 1):
        msg_id = msg_meta["id"]

        # Check if already processed
        if is_already_processed(msg_id):
            print(f"[{idx}/{len(messages)}] [SKIP - ALREADY INDEXED] ID: {msg_id}")
            skipped_count += 1
            continue

        acquire_token(bucket="gmail_api")

        # Sender check
        from_header = fetch_from_header(gmail, msg_id)
        if not is_allowed_sender(from_header):
            print(f"[{idx}/{len(messages)}] [REJECTED SENDER] {from_header}")
            continue

        print(f"[{idx}/{len(messages)}] Processing new email: {msg_id} (From: {from_header}) ...")

        try:
            full_message = (
                gmail.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_id,
                    format="full",
                )
                .execute()
            )

            _index_email(full_message, gmail=gmail)
            new_count += 1
            print(f"   [SUCCESS] Indexed message {msg_id}")

        except Exception as exc:
            print(f"   [ERROR] Failed to process message {msg_id}: {exc}")

    print("\n" + "=" * 65)
    print("Summary:")
    print(f" - Candidate messages checked: {len(messages)}")
    print(f" - Newly indexed emails:        {new_count}")
    print(f" - Already indexed (skipped):   {skipped_count}")
    print("=" * 65)

    # Answers produced from the old content would otherwise be served from cache for
    # up to ANSWER_CACHE_TTL_SECONDS after this run indexed replacements.
    try:
        from services.answer_cache import clear as clear_answer_cache

        cleared = clear_answer_cache()
        if cleared:
            print(f"[*] Cleared {cleared} cached answer(s) invalidated by this sync.")
    except Exception as exc:
        print(f"[*] Answer cache not cleared ({exc}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync new emails since backfill into ASK-AI.")
    parser.add_argument(
        "--user-email",
        type=str,
        default=None,
        help="Sync only this mailbox (default: every mailbox in GMAIL_ACCOUNT_IDS)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default="from:iitj.ac.in",
        help="Gmail search query filter (default: from:iitj.ac.in)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max recent messages to inspect per mailbox (default: 50)",
    )

    args = parser.parse_args()

    mailboxes = [args.user_email] if args.user_email else configured_accounts()
    if not mailboxes:
        print("[!] No mailboxes configured. Set GMAIL_ACCOUNT_IDS=a@iitj.ac.in,b@iitj.ac.in in .env")
        raise SystemExit(1)

    print(f"[*] Syncing {len(mailboxes)} mailbox(es): {', '.join(mailboxes)}")

    for mailbox in mailboxes:
        sync_new_emails(user_email=mailbox, query=args.query, limit=args.limit)
