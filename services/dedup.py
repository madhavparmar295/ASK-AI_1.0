"""
Per-mailbox message-id dedup store.

Records which Gmail message IDs have already been extracted, so a repeated
history/backfill pass does not re-process the same message.

Storage is Redis (already provisioned for Celery) because multiple Celery workers
run concurrently: the previous JSON file store did a read-modify-write of the whole
file on every call, which lost updates under concurrency and re-parsed the entire
ID list per message. The JSON file is still used as a fallback when Redis is
unavailable, and is migrated into Redis once per process.
"""

import json
import os

from services.content_dedup import get_redis

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.getenv("DEDUP_STORE_PATH", "processed_message_ids.json")
STORE_PATH = env_path if os.path.isabs(env_path) else os.path.join(BASE_DIR, env_path)

REDIS_KEY = os.getenv("DEDUP_REDIS_KEY", "askai:dedup:processed_message_ids")

_migrated = False


def _load() -> set:
    if not os.path.exists(STORE_PATH) or os.path.getsize(STORE_PATH) == 0:
        return set()
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return set()


def _save(ids: set) -> None:
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(list(ids), f)


def _migrate_file_into_redis(client) -> None:
    """One-time per process: seed Redis from the legacy JSON store."""
    global _migrated
    if _migrated:
        return

    _migrated = True
    try:
        if client.scard(REDIS_KEY) > 0:
            return
        existing = _load()
        if not existing:
            return
        pipe = client.pipeline()
        for message_id in existing:
            pipe.sadd(REDIS_KEY, message_id)
        pipe.execute()
        print(f"[Dedup] Migrated {len(existing)} message IDs from {os.path.basename(STORE_PATH)} into Redis.")
    except Exception as exc:
        print(f"[Dedup] Message ID migration skipped ({exc}).")


def is_already_processed(message_id: str) -> bool:
    client = get_redis()
    if client is None:
        return message_id in _load()

    try:
        _migrate_file_into_redis(client)
        return bool(client.sismember(REDIS_KEY, message_id))
    except Exception as exc:
        print(f"[Dedup] Redis lookup failed ({exc}); falling back to the JSON store.")
        return message_id in _load()


def mark_processed(message_id: str) -> None:
    client = get_redis()
    if client is None:
        ids = _load()
        ids.add(message_id)
        _save(ids)
        return

    try:
        client.sadd(REDIS_KEY, message_id)
    except Exception as exc:
        print(f"[Dedup] Redis write failed ({exc}); falling back to the JSON store.")
        ids = _load()
        ids.add(message_id)
        _save(ids)


def clear_dedup_store() -> None:
    """Wipe both stores. Kept for the admin/debug endpoint in routers/auth.py."""
    client = get_redis()
    if client is not None:
        try:
            client.delete(REDIS_KEY)
        except Exception as exc:
            print(f"[Dedup] Could not clear the Redis store ({exc}).")
    _save(set())


def store_size() -> int:
    """How many message IDs are currently recorded (Redis when available)."""
    client = get_redis()
    if client is not None:
        try:
            return int(client.scard(REDIS_KEY))
        except Exception:
            pass
    return len(_load())
