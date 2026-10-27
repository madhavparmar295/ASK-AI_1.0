"""
Answer cache.

The same questions recur constantly on a campus ("when is the mess bill due?"), and
each one costs an embedding, two searches, a rerank and an LLM call. Identical
questions are answered from cache within a short window.

The scope is part of the key. A cached answer is only ever returned to a caller with
the same access scope as the caller who produced it, because two users asking the
same words are not entitled to the same documents.

Cache entries are dropped when content is re-ingested (see ``clear``), so a corrected
document does not keep serving a stale answer.

    ANSWER_CACHE_ENABLED=true
    ANSWER_CACHE_TTL_SECONDS=3600
    ANSWER_CACHE_MAX_ENTRIES=2000     (in-process fallback only)
"""

import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict

from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger("askai.cache")

ENABLED = os.getenv("ANSWER_CACHE_ENABLED", "true").lower() not in ("0", "false", "no")
TTL_SECONDS = float(os.getenv("ANSWER_CACHE_TTL_SECONDS", "3600"))
MAX_ENTRIES = int(os.getenv("ANSWER_CACHE_MAX_ENTRIES", "2000"))
REDIS_PREFIX = os.getenv("ANSWER_CACHE_PREFIX", "askai:answer_cache")

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")

_memory: OrderedDict[str, tuple[float, str]] = OrderedDict()

stats = {"hits": 0, "misses": 0, "stores": 0}


def normalize(question: str) -> str:
    """Collapse the differences that do not change the question's meaning."""
    text = (question or "").strip().casefold()
    text = _PUNCT_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def cache_key(question: str, scope: str) -> str:
    """Key over question *and* access scope, so answers cannot cross scopes."""
    digest = hashlib.sha256(f"{scope}|{normalize(question)}".encode("utf-8")).hexdigest()
    return f"{REDIS_PREFIX}:{digest}"


def _redis():
    try:
        from services.content_dedup import get_redis

        return get_redis()
    except Exception:
        return None


def get(question: str, scope: str) -> dict | None:
    """Return the cached payload, or None."""
    if not ENABLED or not question:
        return None

    key = cache_key(question, scope)
    client = _redis()

    if client is not None:
        try:
            raw = client.get(key)
            if raw:
                stats["hits"] += 1
                return json.loads(raw)
            stats["misses"] += 1
            return None
        except Exception as exc:
            _logger.warning("redis answer cache read failed: %s", exc)

    entry = _memory.get(key)
    if entry is None:
        stats["misses"] += 1
        return None

    stored_at, raw = entry
    if time.time() - stored_at > TTL_SECONDS:
        _memory.pop(key, None)
        stats["misses"] += 1
        return None

    _memory.move_to_end(key)
    stats["hits"] += 1
    return json.loads(raw)


def set(question: str, scope: str, payload: dict, ttl: float | None = None) -> None:
    """Store an answer payload."""
    if not ENABLED or not question:
        return

    try:
        raw = json.dumps(payload, default=str)
    except (TypeError, ValueError) as exc:
        _logger.warning("answer payload not cacheable: %s", exc)
        return

    key = cache_key(question, scope)
    client = _redis()

    if client is not None:
        try:
            client.set(key, raw, ex=int(ttl or TTL_SECONDS))
            stats["stores"] += 1
            return
        except Exception as exc:
            _logger.warning("redis answer cache write failed: %s", exc)

    _memory[key] = (time.time(), raw)
    _memory.move_to_end(key)
    while len(_memory) > MAX_ENTRIES:
        _memory.popitem(last=False)
    stats["stores"] += 1


def clear() -> int:
    """
    Drop every cached answer.

    Called after ingestion so a corrected or re-chunked document is not shadowed by
    an answer produced from the old text.
    """
    client = _redis()
    removed = 0

    if client is not None:
        try:
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor=cursor, match=f"{REDIS_PREFIX}:*", count=500)
                if keys:
                    client.delete(*keys)
                    removed += len(keys)
                if cursor == 0:
                    break
        except Exception as exc:
            _logger.warning("redis answer cache clear failed: %s", exc)

    removed += len(_memory)
    _memory.clear()
    return removed


def info() -> dict:
    client = _redis()
    return {
        "enabled": ENABLED,
        "backend": "redis" if client is not None else "memory",
        "ttl_seconds": TTL_SECONDS,
        "memory_entries": len(_memory),
        "hits": stats["hits"],
        "misses": stats["misses"],
        "stores": stats["stores"],
    }
