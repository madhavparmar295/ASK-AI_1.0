"""
Document usage tracking.

Retention is driven by "when was this document last used", so every retrieval
stamps the documents it answered from. Two places are written:

    Pinecone metadata   ``last_used`` (epoch seconds), one bulk request per query
    Redis               a sorted set scored by the same timestamp

The retention task treats a document as abandoned only when both agree. The
Pinecone write is best effort by design, and a failed one must never leave a
document that is still being asked about looking unused.
"""

import os
import time

from services.content_dedup import get_redis
from services.vectorstore import touch_documents

USAGE_ENABLED = os.getenv("USAGE_TRACKING_ENABLED", "true").lower() not in ("0", "false", "no")
USAGE_KEY = os.getenv("USAGE_REDIS_KEY", "askai:usage:documents")


def record_usage(doc_ids: list[str], when: float | None = None) -> int:
    """
    Record that these documents were just used to answer a question.

    Never raises: usage tracking must not be able to break answering.
    """
    if not USAGE_ENABLED:
        return 0

    unique = [doc_id for doc_id in dict.fromkeys(doc_ids) if doc_id]
    if not unique:
        return 0

    timestamp = float(when if when is not None else time.time())

    recorded = 0
    client = get_redis()
    if client is not None:
        try:
            mapping = {doc_id: timestamp for doc_id in unique}
            client.zadd(USAGE_KEY, mapping)
            recorded = len(unique)
        except Exception as exc:
            print(f"[Usage] Could not record usage in Redis: {exc}")

    try:
        touch_documents(unique, when=timestamp)
    except Exception as exc:  # touch_documents already swallows; belt and braces
        print(f"[Usage] Could not record usage in Pinecone metadata: {exc}")

    return recorded


def recently_used_doc_ids(since: float) -> set[str]:
    """
    Documents used at or after ``since``.

    Raises RuntimeError when Redis is unavailable. The retention task relies on
    this set to protect documents the metadata stamp failed to update, so it must
    refuse to run rather than risk deleting live content.
    """
    client = get_redis()
    if client is None:
        raise RuntimeError(
            "Redis is unavailable, so recently used documents cannot be established."
        )

    try:
        return set(client.zrangebyscore(USAGE_KEY, since, "+inf"))
    except Exception as exc:
        raise RuntimeError(f"Could not read usage timestamps from Redis: {exc}") from exc


def usage_stats() -> dict:
    """Counts for reporting: how many documents have usage timestamps."""
    client = get_redis()
    if client is None:
        return {"available": False, "tracked_documents": 0}

    try:
        return {"available": True, "tracked_documents": int(client.zcard(USAGE_KEY))}
    except Exception as exc:
        return {"available": False, "error": str(exc), "tracked_documents": 0}


def forget_usage(doc_ids: list[str]) -> int:
    """Drop usage timestamps for deleted documents so the set cannot grow forever."""
    unique = [doc_id for doc_id in dict.fromkeys(doc_ids) if doc_id]
    if not unique:
        return 0

    client = get_redis()
    if client is None:
        return 0

    try:
        return int(client.zrem(USAGE_KEY, *unique))
    except Exception as exc:
        print(f"[Usage] Could not drop usage timestamps: {exc}")
        return 0
