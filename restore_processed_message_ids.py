"""
Rebuild processed_message_ids.json from data the pipeline already produced.

The dedup store is a derived list: every Gmail message that was extracted is
recorded only here, so losing it means a future backfill re-processes and
re-embeds mail. It is recoverable because message IDs double as doc_ids:

    email body        doc_id = "<message_id>"
    email attachment  doc_id = "<message_id>:<filename>"

Sources merged into the file (union, never destructive):
    - the existing file
    - Pinecone vector IDs (doc_id prefix)
    - PostgreSQL ``documents.doc_id`` when the database is reachable, which also
      covers messages that were stored but never made it into Pinecone

    python restore_processed_message_ids.py            # rebuild and report
    python restore_processed_message_ids.py --dry-run   # report only
"""

import argparse
import json
import os
import re
import sys

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

load_dotenv(override=True)

# Gmail message IDs are 16 hexadecimal characters.
MESSAGE_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


def _store_path() -> str:
    env_path = os.getenv("DEDUP_STORE_PATH", "processed_message_ids.json")
    return env_path if os.path.isabs(env_path) else os.path.join(BASE_DIR, env_path)


def message_id_from_doc_id(doc_id: str) -> str | None:
    """Extract a Gmail message ID from a pipeline doc_id, if there is one."""
    prefix = str(doc_id or "").split(":", 1)[0]
    return prefix if MESSAGE_ID_PATTERN.match(prefix) else None


def load_existing(path: str) -> set[str]:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return {str(item) for item in json.load(f)}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return set()


def from_pinecone() -> set[str]:
    from services.vectorstore import get_index

    found: set[str] = set()
    for page in get_index().list():
        for vector in page.vectors:
            raw_id = getattr(vector, "id", None) or str(vector)
            doc_id = str(raw_id).rsplit("-", 1)[0]
            message_id = message_id_from_doc_id(doc_id)
            if message_id:
                found.add(message_id)
    return found


def from_postgres() -> set[str]:
    from services.postgres import get_conn

    found: set[str] = set()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT doc_id FROM documents;")
            for (doc_id,) in cur.fetchall():
                message_id = message_id_from_doc_id(doc_id)
                if message_id:
                    found.add(message_id)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the processed message ID store.")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    args = parser.parse_args()

    path = _store_path()
    existing = load_existing(path)
    print(f"[*] Store: {path} ({len(existing)} message IDs present)")

    recovered = set()
    for label, loader in (("Pinecone", from_pinecone), ("PostgreSQL", from_postgres)):
        try:
            found = loader()
        except Exception as exc:
            print(f"[!] {label} source unavailable: {exc}")
            continue
        new_ids = found - existing
        recovered |= found
        print(f"[*] {label}: {len(found)} message IDs, {len(new_ids)} not in the store")

    merged = sorted(existing | recovered)
    print(f"[*] Merged total: {len(merged)} message IDs")

    if args.dry_run:
        print("[*] Dry run: nothing written.")
        return

    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f)
    print(f"[*] Wrote {len(merged)} message IDs to {path}")

    # Seed Redis as well. services/dedup.py only migrates the file when the Redis
    # set is still empty, so restoring the file after the app has started would
    # otherwise leave the newly recovered IDs out of the live store.
    from services.dedup import REDIS_KEY, get_redis

    client = get_redis()
    if client is None:
        print("[!] Redis unavailable: the file will be migrated on first use.")
        return

    try:
        pipe = client.pipeline()
        for message_id in merged:
            pipe.sadd(REDIS_KEY, message_id)
        pipe.execute()
        print(f"[*] Redis '{REDIS_KEY}' now holds {client.scard(REDIS_KEY)} message IDs")
    except Exception as exc:
        print(f"[!] Could not seed Redis: {exc}")


if __name__ == "__main__":
    main()
