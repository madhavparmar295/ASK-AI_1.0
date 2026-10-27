"""The chatbot's half of the grievance form's "before you submit" hint.

The grievance screens call ``POST /chat/api/ask`` with the description the student has
typed and show the answer above the submit button, clearly labelled as an automated
suggestion. Contract: ``docs/CHATBOT_INTEGRATION.md`` in the grievance system.

Three rules make it safe to put next to a complaint form:

* Nothing is answered for text the grievance classifier considers sensitive. The form
  already refuses to call this endpoint for such text; this is the second check, so a
  future caller cannot skip it.
* Nothing about the text is logged. This path calls the two retrievers directly
  instead of the full pipeline, so the query never reaches the retrieval log; this
  module logs only counts, latency and a grounded flag.
* A failure, a timeout or an ungrounded answer returns an empty answer. The form then
  shows nothing, which is the right outcome for a hint that "may help".
"""

from __future__ import annotations

import logging
import os
import threading
import time

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from grievance_app.services.classifier import flags as grievance_flags
from services import rag
from services.access_control import resolve_user_tag
from services.rate_limiter import try_acquire
from services.retrieval import (
    dense_search,
    lexical_search,
    reciprocal_rank_fusion,
)

router = APIRouter(prefix="/chat/api", tags=["grievance"])

_logger = logging.getLogger("askai.grievance_hint")

# Deadline for the whole hint. The form waits 13 s for this, so 12 s is inside it.
# 7.5 s used to be the cap and it lost the first request after every restart: the
# hosted embedding call alone measured ~4.9 s cold, plus ~1.5 s for the answer.
HINT_TIMEOUT_SECONDS = float(os.getenv("GRIEVANCE_HINT_TIMEOUT_SECONDS", "12"))
# Vector search gets this long; keyword search is local and effectively instant, so
# when the embedding service is cold the hint proceeds on keyword evidence instead of
# returning nothing. The dense result is still used when it arrives in time.
HINT_DENSE_BUDGET_SECONDS = float(os.getenv("GRIEVANCE_HINT_DENSE_BUDGET_SECONDS", "4"))
MIN_TEXT_CHARS = 25
MAX_TEXT_CHARS = 2000
MAX_SOURCES = 5
# Chunks handed to the answer model. Enough for a policy answer, few enough that the
# prompt stays small and the model answers quickly.
HINT_TOP_CHUNKS = int(os.getenv("GRIEVANCE_HINT_TOP_CHUNKS", "6"))
# A hint is a paragraph, not an essay. Capping the answer is most of the latency.
HINT_MAX_ANSWER_TOKENS = int(os.getenv("GRIEVANCE_HINT_MAX_ANSWER_TOKENS", "220"))

# Per client address. The grievance form asks once per pause in typing, so a person
# writing a paragraph uses a handful of these.
HINT_CAPACITY = int(os.getenv("GRIEVANCE_HINT_CAPACITY", "20"))
HINT_REFILL = float(os.getenv("GRIEVANCE_HINT_REFILL_PER_SECOND", "0.1"))


class HintRequest(BaseModel):
    text: str = Field(default="", max_length=5000)


EMPTY = {"answer": "", "sources": []}


def _is_sensitive(text: str) -> bool:
    """Raise the same confidential flag the grievance ticket form uses."""
    try:
        return bool(grievance_flags(text)["confidential"])
    except Exception:                      # a broken screen must never leak text onward
        return True


def _call_with_timeout(function, timeout: float):
    """Run a blocking function on a daemon thread and give up after `timeout` seconds.

    Threads cannot be cancelled in Python, so a slow model call finishes in the
    background and its result is discarded. That is acceptable here: the request has
    already returned an empty hint, and the thread dies with the process.
    """
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = function()
        except BaseException as exc:        # handed to the waiting thread below
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True, name="grievance-hint")
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError("the answer did not arrive in time")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _context_chunks(matches: list[dict]) -> list[dict]:
    keys = ("text", "doc_id", "access_level", "sender", "subject", "date", "source_type", "filename", "source")
    return [
        {**{key: (match.get("metadata") or {}).get(key, "") for key in keys},
         "score": match.get("score", 0.0)}
        for match in matches
    ]


def _sources(matches: list[dict], cited: list[int]) -> list[dict]:
    """At most five sources, only the ones the answer actually cited."""
    out: list[dict] = []
    for number, match in enumerate(matches, start=1):
        if cited and number not in cited:
            continue
        metadata = match.get("metadata") or {}
        title = metadata.get("subject") or metadata.get("filename") or metadata.get("sender") or "College document"
        url = str(metadata.get("source") or "")
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("/")):
            url = ""
        out.append(
            {
                "title": str(title)[:200],
                "section": str(metadata.get("section") or "")[:100],
                "url": url,
            }
        )
        if len(out) == MAX_SOURCES:
            break
    return out


# One vector search at a time. When a hint gives up on a slow embedding, that call keeps
# running in the background; starting another one for the next keystroke piles them up
# and slows everything down. The second hint uses keyword evidence instead and the
# abandoned result is simply dropped.
_DENSE_IN_FLIGHT = threading.Lock()


def _dense_if_idle(text: str, user_tag: str) -> list[dict] | None:
    if not _DENSE_IN_FLIGHT.acquire(blocking=False):
        return None
    try:
        return dense_search(text, user_tag, top_k=12)
    finally:
        _DENSE_IN_FLIGHT.release()


def _background(function):
    """Start `function` on a daemon thread; returns (thread, box) where box holds value/error."""
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = function()
        except BaseException as exc:        # read by the caller
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True, name="grievance-hint-work")
    thread.start()
    return thread, box


def _fast_matches(text: str) -> list[dict]:
    """Dense + keyword retrieval, fused, without the slow stages.

    The chatbot's full pipeline rewrites the query with a model, reranks with a
    cross-encoder and then fetches neighbouring chunks; on a real corpus that measured
    12-30 seconds. This path keeps the two retrievers and the fusion (exact terms still
    matter) and drops the rest.

    Dense search is started first but only waited for up to HINT_DENSE_BUDGET_SECONDS.
    Keyword search needs no network, so a cold embedding service costs relevance, not
    the whole hint.
    """
    user_tag = resolve_user_tag("")
    started = time.time()
    dense_thread, dense_box = _background(lambda: _dense_if_idle(text, user_tag))
    lexical = lexical_search(text, user_tag, limit=12)
    lexical_ms = round((time.time() - started) * 1000, 1)

    dense_thread.join(HINT_DENSE_BUDGET_SECONDS)
    dense = dense_box.get("value") or []
    dense_ready = not dense_thread.is_alive()
    if dense_ready and dense_box.get("error") is not None:
        _logger.warning("hint dense search failed", extra={"error": str(dense_box["error"])[:160]})

    _logger.info(
        "hint retrieval",
        extra={
            "lexical_ms": lexical_ms,
            "dense_ready": dense_ready,
            "dense": len(dense),
            "lexical": len(lexical),
        },
    )
    return reciprocal_rank_fusion({"dense": dense, "lexical": lexical})[:HINT_TOP_CHUNKS]


def _answer(text: str) -> dict:
    """Retrieve and answer. Only a grounded answer is returned."""
    matches = _fast_matches(text)
    if not matches:
        return EMPTY
    chunks = _context_chunks(matches)
    result = rag.answer_question(text, chunks, history=None, max_tokens=HINT_MAX_ANSWER_TOKENS)
    if not result.get("grounded"):
        return EMPTY
    return {"answer": result["answer"], "sources": _sources(matches, result.get("cited_sources") or [])}


@router.post("/ask", summary="Answer a problem description for the grievance form")
def ask_for_hint(body: HintRequest, request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"

    text = (body.text or "").strip()
    if len(text) < MIN_TEXT_CHARS:
        return EMPTY
    text = text[:MAX_TEXT_CHARS]

    client = getattr(request.client, "host", "unknown")
    if not try_acquire(f"grievance-hint:{client}", capacity=HINT_CAPACITY, refill_rate=HINT_REFILL):
        _logger.info("hint rate limited")
        return EMPTY

    if _is_sensitive(text):
        _logger.info("hint skipped: sensitive text")
        return EMPTY

    started = time.time()
    try:
        answer = _call_with_timeout(lambda: _answer(text), HINT_TIMEOUT_SECONDS)
    except TimeoutError:
        _logger.warning("hint timed out", extra={"after_seconds": HINT_TIMEOUT_SECONDS})
        return EMPTY
    except Exception:
        _logger.exception("hint failed")
        return EMPTY

    _logger.info(
        "hint answered",
        extra={
            "latency_ms": round((time.time() - started) * 1000, 1),
            "grounded": bool(answer["answer"]),
            "sources": len(answer["sources"]),
        },
    )
    return answer
