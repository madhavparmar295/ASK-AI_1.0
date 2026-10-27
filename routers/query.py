"""
Question answering endpoints.

    POST /query/ask          one JSON response, cached where possible
    POST /query/ask/stream   server-sent events: sources first, then answer tokens

Both paths share the same retrieval, memory and grounding behaviour. What changed
from the previous single handler:

    * per-scope rate limiting, so one client cannot exhaust a shared LLM quota
    * retrieval and answer generation run in a worker thread; they are blocking
      network calls, and running them in the event loop serialised every concurrent
      request behind the slowest one
    * an answer cache, keyed by question *and* access scope
    * recent conversation turns, so follow-up questions have a referent
    * citations and a grounded flag, so an uncited answer is visibly uncited
    * an LLM outage answers 503 instead of returning an exception trace
"""

import json
import logging
import os
import time

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from schemas.query import QueryRequest, QueryResponse, SourceChunk
from services import answer_cache, conversation, rag
from services.access_control import resolve_user_tag
from services.llm import LLMError
from services.rate_limiter import retry_after_seconds, try_acquire
from services.retrieval import TOP_CHUNKS, retrieve_chunks

router = APIRouter(prefix="/query", tags=["query"])

_logger = logging.getLogger("askai.query")

# Tokens refill at 0.05/s (three a minute) with a burst of 30: generous for a person
# reading answers, tight enough that a script cannot spend the whole LLM budget.
ASK_CAPACITY = int(os.getenv("ASK_RATE_CAPACITY", "30"))
ASK_REFILL = float(os.getenv("ASK_RATE_REFILL_PER_SECOND", "0.05"))
CACHE_ONLY_GROUNDED = os.getenv("ANSWER_CACHE_ONLY_GROUNDED", "true").lower() not in ("0", "false", "no")


def _scope(request: QueryRequest) -> str:
    """Access scope for caching: same tag and same domain see the same documents."""
    domain = (request.user_email or "").split("@")[-1].lower()
    return f"{resolve_user_tag(domain)}:{domain}"


def _enforce_rate_limit(scope: str) -> None:
    bucket = f"ask:{scope}"
    if try_acquire(bucket, capacity=ASK_CAPACITY, refill_rate=ASK_REFILL):
        return

    wait = retry_after_seconds(bucket, refill_rate=ASK_REFILL)
    _logger.warning("ask rate limit hit", extra={"scope": scope, "retry_after": wait})
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many questions in a short time. Please wait a moment and try again.",
        headers={"Retry-After": str(int(wait) or 1)},
    )


def _context_chunks(matches: list[dict]) -> list[dict]:
    """Shape retrieved matches for the prompt."""
    return [
        {
            "text": match.get("metadata", {}).get("text", ""),
            "score": match.get("score", 0.0),
            "doc_id": match.get("metadata", {}).get("doc_id", ""),
            "access_level": match.get("metadata", {}).get("access_level", "public"),
            "sender": match.get("metadata", {}).get("sender", ""),
            "subject": match.get("metadata", {}).get("subject", ""),
            "date": match.get("metadata", {}).get("date", ""),
            "source_type": match.get("metadata", {}).get("source_type", "unknown"),
            "filename": match.get("metadata", {}).get("filename", ""),
            "source": match.get("metadata", {}).get("source", ""),
        }
        for match in matches
    ]


def _sources(matches: list[dict]) -> list[SourceChunk]:
    return [
        SourceChunk(
            text=match.get("metadata", {}).get("text", ""),
            score=match.get("score", 0.0),
            doc_id=match.get("metadata", {}).get("doc_id", ""),
            access_level=match.get("metadata", {}).get("access_level", "public"),
            sender=match.get("metadata", {}).get("sender"),
            subject=match.get("metadata", {}).get("subject"),
            date=match.get("metadata", {}).get("date"),
            source=match.get("metadata", {}).get("source") or match.get("metadata", {}).get("filename"),
            source_type=match.get("metadata", {}).get("source_type"),
            filename=match.get("metadata", {}).get("filename"),
        )
        for match in matches
    ]


@router.post("/ask", response_model=QueryResponse)
async def ask_question(
    request: QueryRequest,
    http_request: Request,
    response: Response,
) -> QueryResponse:
    """Answer a question from the indexed documents."""
    started = time.time()
    scope = _scope(request)
    request_id = getattr(http_request.state, "request_id", "")

    # Validate before spending a rate-limit token: an empty question is the caller's
    # mistake, not usage of the shared quota.
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question is empty.")

    _enforce_rate_limit(scope)

    cached = answer_cache.get(question, scope)
    if cached:
        response.headers["X-Cache"] = "HIT"
        _log_answer(
            question,
            scope,
            request_id,
            started,
            cached=True,
            grounded=bool(cached.get("grounded")),
            sources=len(cached.get("sources") or []),
            answer=cached.get("answer") or "",
        )
        return QueryResponse(**cached, cached=True)

    response.headers["X-Cache"] = "MISS"

    user_tag = resolve_user_tag((request.user_email or "").split("@")[-1])
    history = conversation.get_history(request.session_id)

    try:
        matches = await run_in_threadpool(
            retrieve_chunks,
            question,
            user_tag,
            TOP_CHUNKS,
            request.session_id,
        )
        result = await run_in_threadpool(
            rag.answer_question,
            question,
            _context_chunks(matches),
            history,
        )
    except LLMError as exc:
        _logger.error("llm unavailable", extra={"request_id": request_id, "error": str(exc)[:200]})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The answering model is temporarily unavailable. Please try again.",
        )

    payload = QueryResponse(
        question=question,
        answer=result["answer"],
        sources=_sources(matches),
        grounded=result["grounded"],
        cited_sources=result["cited_sources"],
        cached=False,
        answer_latency_ms=result["latency_ms"],
        session_id=request.session_id,
    )

    conversation.record_turn(request.session_id, question, result["answer"])

    if not CACHE_ONLY_GROUNDED or result["grounded"]:
        answer_cache.set(question, scope, payload.model_dump(exclude={"cached"}))

    _log_answer(
        question,
        scope,
        request_id,
        started,
        cached=False,
        grounded=result["grounded"],
        sources=len(matches),
        cited=len(result["cited_sources"]),
        answer=result["answer"],
    )
    return payload


@router.post(
    "/ask/stream",
    response_class=StreamingResponse,
    summary="Answer a question, streaming the answer as server-sent events",
)
async def ask_question_stream(request: QueryRequest, http_request: Request) -> StreamingResponse:
    """
    Stream an answer.

    Events, one JSON object per ``data:`` line:

        {"type": "sources", "sources": [...]}
        {"type": "token", "text": "..."}
        {"type": "done", "grounded": true, "cited_sources": [1, 3], "cached": false}
        {"type": "error", "detail": "..."}

    Sources are sent before the first token so the client can render citations that
    the answer refers to as it arrives.
    """
    started = time.time()
    scope = _scope(request)
    request_id = getattr(http_request.state, "request_id", "")

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question is empty.")

    _enforce_rate_limit(scope)

    cached = answer_cache.get(question, scope)
    user_tag = resolve_user_tag((request.user_email or "").split("@")[-1])
    history = conversation.get_history(request.session_id)

    if cached:
        matches: list[dict] = []
        sources_payload = cached.get("sources") or []
        answer_text = cached.get("answer") or ""
    else:
        try:
            matches = await run_in_threadpool(
                retrieve_chunks,
                question,
                user_tag,
                TOP_CHUNKS,
                request.session_id,
            )
        except Exception as exc:  # retrieval degrades rather than failing the request
            _logger.error("retrieval failed", extra={"request_id": request_id, "error": str(exc)[:200]})
            matches = []
        sources_payload = [source.model_dump() for source in _sources(matches)]
        answer_text = ""

    async def event_stream():
        def emit(event: dict) -> str:
            return f"data: {json.dumps(event, default=str)}\n\n"

        yield emit({"type": "sources", "sources": sources_payload, "cached": bool(cached)})

        if cached:
            yield emit({"type": "token", "text": answer_text})
            yield emit(
                {
                    "type": "done",
                    "grounded": bool(cached.get("grounded")),
                    "cited_sources": cached.get("cited_sources") or [],
                    "cached": True,
                }
            )
            return

        chunks = _context_chunks(matches)
        collected: list[str] = []

        try:
            # The model client is blocking, so it is consumed on a worker thread and
            # the tokens are pushed to the client as they are produced.
            async for piece in iterate_in_threadpool(rag.stream_answer(question, chunks, history)):
                collected.append(piece)
                yield emit({"type": "token", "text": piece})
        except LLMError as exc:
            _logger.error("stream failed", extra={"request_id": request_id, "error": str(exc)[:200]})
            yield emit(
                {
                    "type": "error",
                    "detail": "The answering model is temporarily unavailable. Please try again.",
                }
            )
            return

        answer = "".join(collected)
        cited = rag.extract_citations(answer, chunks)
        not_found = rag.is_not_found(answer)
        grounded = bool(cited) and not not_found

        final_answer = rag.build_fallback_message(question) if not_found else answer
        conversation.record_turn(request.session_id, question, final_answer)
        if not CACHE_ONLY_GROUNDED or grounded:
            answer_cache.set(
                question,
                scope,
                {
                    "question": question,
                    "answer": final_answer,
                    "sources": sources_payload,
                    "grounded": grounded,
                    "cited_sources": cited,
                    "session_id": request.session_id,
                },
            )

        _log_answer(question, scope, request_id, started, cached=False, grounded=grounded, sources=len(matches), cited=len(cited), answer=answer)
        yield emit(
            {
                "type": "done",
                "grounded": grounded,
                "cited_sources": cited,
                "cached": False,
                "answer_latency_ms": round((time.time() - started) * 1000, 1),
            }
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Cache": "HIT" if cached else "MISS"},
    )


@router.get("/cache", summary="Answer cache statistics")
def cache_stats() -> dict:
    """Cache state. Useful when judging whether answers are being reused."""
    return {"answer_cache": answer_cache.info(), "conversation": conversation.info()}


@router.post("/cache/clear", summary="Clear cached answers")
def cache_clear(confirm: bool = Query(False, description="must be true")) -> dict:
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pass confirm=true to clear the answer cache.",
        )
    return {"cleared": answer_cache.clear()}


def _log_answer(
    question: str,
    scope: str,
    request_id: str,
    started: float,
    cached: bool,
    grounded: bool,
    sources: int,
    cited: int = 0,
    answer: str = "",
) -> None:
    try:
        from services.logging_config import log_answer

        log_answer(
            question=question,
            answer=answer,
            latency_ms=round((time.time() - started) * 1000, 1),
            grounded=grounded,
            source_count=sources,
            request_id=request_id,
        )
        _logger.info(
            "ask",
            extra={
                "request_id": request_id,
                "scope": scope,
                "cached": cached,
                "grounded": grounded,
                "sources": sources,
                "cited": cited,
                "latency_ms": round((time.time() - started) * 1000, 1),
            },
        )
    except Exception:
        pass
