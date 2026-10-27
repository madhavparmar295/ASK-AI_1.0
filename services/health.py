"""
Health and readiness checks.

``/health`` is a liveness probe: it answers without touching anything external, so
it stays cheap and never restarts a healthy process because a dependency blipped.

``/health/ready`` reports the dependencies, cached briefly so a frequent probe does
not hammer Pinecone:

    pinecone    required - the document index is the retrieval store
    database    optional - chat history, users and feedback degrade if it is down
    redis       optional - dedup ledger, usage tracking and the answer cache
"""

import os
import time

from dotenv import load_dotenv

load_dotenv()

READINESS_CACHE_SECONDS = float(os.getenv("HEALTH_CACHE_SECONDS", "30"))

_cache: dict = {"at": 0.0, "report": None}


def _check_database() -> dict:
    try:
        from sqlalchemy import text

        from database import engine

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _check_redis() -> dict:
    try:
        from services.content_dedup import get_redis

        client = get_redis()
        if client is None:
            return {"ok": False, "error": "unavailable"}
        client.ping()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _check_pinecone() -> dict:
    try:
        from services.vectorstore import get_index

        stats = get_index().describe_index_stats()
        return {"ok": True, "vectors": int(stats.total_vector_count)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def readiness_report(force: bool = False) -> dict:
    """Dependency status. Pinecone decides readiness; the rest is reported."""
    now = time.time()
    if (
        not force
        and _cache["report"] is not None
        and now - _cache["at"] < READINESS_CACHE_SECONDS
    ):
        return _cache["report"]

    checks = {
        "pinecone": _check_pinecone(),
        "database": _check_database(),
        "redis": _check_redis(),
    }

    failing_required = [name for name in ("pinecone",) if not checks[name]["ok"]]
    degraded = [name for name, result in checks.items() if not result["ok"] and name != "pinecone"]

    report = {
        "ready": not failing_required,
        "degraded": degraded,
        "checks": checks,
        "cached_seconds": READINESS_CACHE_SECONDS,
    }

    _cache["report"] = report
    _cache["at"] = now
    return report
