"""
Short-term conversation memory.

A follow-up question ("and the second one?", "what about the hostel form?") is
unanswerable without the previous turns. Chat history is already persisted by
``/chat/api/save`` for the sidebar, but reading the full session out of Postgres on
every question couples asking to the database and replays a whole conversation into
the prompt.

This keeps a bounded, recent transcript per session: Redis when it is available (so
it survives a restart and is shared between workers), otherwise an in-process store
that is enough for a single-instance deployment.

    CONVERSATION_MEMORY_TURNS=4        # turns kept per session
    CONVERSATION_MEMORY_TTL=7200       # seconds
"""

import json
import logging
import os
import time
from collections import OrderedDict, deque

from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger("askai.conversation")

TURNS = int(os.getenv("CONVERSATION_MEMORY_TURNS", "4"))
TTL_SECONDS = int(os.getenv("CONVERSATION_MEMORY_TTL", "7200"))
REDIS_PREFIX = os.getenv("CONVERSATION_MEMORY_PREFIX", "askai:conversation")
MAX_SESSIONS = int(os.getenv("CONVERSATION_MEMORY_MAX_SESSIONS", "500"))

_memory: OrderedDict[str, deque] = OrderedDict()


def _redis():
    try:
        from services.content_dedup import get_redis

        return get_redis()
    except Exception:
        return None


def _key(session_id: str) -> str:
    return f"{REDIS_PREFIX}:{session_id}"


def record_turn(session_id: str | None, question: str, answer: str) -> None:
    """Append a question/answer pair to a session's recent history."""
    if not session_id or not question:
        return

    turns = [
        {"role": "user", "content": question[:2000]},
        {"role": "assistant", "content": (answer or "")[:2000]},
    ]

    client = _redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            for turn in turns:
                pipe.rpush(_key(session_id), json.dumps(turn))
            pipe.ltrim(_key(session_id), -TURNS * 2, -1)
            pipe.expire(_key(session_id), TTL_SECONDS)
            pipe.execute()
            return
        except Exception as exc:
            _logger.warning("redis conversation write failed: %s", exc)

    history = _memory.get(session_id)
    if history is None:
        history = deque(maxlen=TURNS * 2)
        _memory[session_id] = history
    history.extend(turns)
    _memory.move_to_end(session_id)
    while len(_memory) > MAX_SESSIONS:
        _memory.popitem(last=False)


def get_history(session_id: str | None) -> list[dict]:
    """Recent turns for a session, oldest first."""
    if not session_id:
        return []

    client = _redis()
    if client is not None:
        try:
            raw_turns = client.lrange(_key(session_id), -TURNS * 2, -1)
            turns = []
            for raw in raw_turns:
                try:
                    turns.append(json.loads(raw))
                except (TypeError, ValueError):
                    continue
            return turns
        except Exception as exc:
            _logger.warning("redis conversation read failed: %s", exc)

    return list(_memory.get(session_id, []))


def forget(session_id: str | None) -> None:
    """Drop a session's memory (used when a chat is deleted or cleared)."""
    if not session_id:
        return

    client = _redis()
    if client is not None:
        try:
            client.delete(_key(session_id))
        except Exception:
            pass
    _memory.pop(session_id, None)


def info() -> dict:
    client = _redis()
    return {
        "backend": "redis" if client is not None else "memory",
        "turns": TURNS,
        "ttl_seconds": TTL_SECONDS,
        "sessions_in_memory": len(_memory),
    }
