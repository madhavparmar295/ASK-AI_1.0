"""
Structured logging for the API and the workers.

JSON lines by default so logs can be shipped and searched, with a plain-text mode
for local development.

Every request gets a request id: it is returned in the ``X-Request-ID`` header and
included in the request log line, which makes it possible to trace one user's slow
or wrong answer across the app, the retrieval logs and the workers.

    LOG_FORMAT=json|text   (default json)
    LOG_LEVEL=INFO         (default INFO)
    LOG_REQUESTS=true      (default true)
"""

import json
import logging
import os
import sys
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

LOG_FORMAT = os.getenv("LOG_FORMAT", "json").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_REQUESTS = os.getenv("LOG_REQUESTS", "true").lower() not in ("0", "false", "no")

_REQUEST_LOGGER = logging.getLogger("askai.request")

# Log-record attributes that are part of the logging machinery rather than payload.
_STANDARD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
    "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS and not key.startswith("_")
        }
        suffix = f" {extras}" if extras else ""
        return (
            f"{time.strftime('%H:%M:%S', time.localtime(record.created))} "
            f"{record.levelname:<8} {record.name}: {record.getMessage()}{suffix}"
        )


def configure_logging() -> None:
    """Install the root handler. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if LOG_FORMAT == "json" else TextFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(LOG_LEVEL)

    # Uvicorn's access log duplicates the request log below.
    logging.getLogger("uvicorn.access").disabled = LOG_REQUESTS
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))


def log_event(logger: logging.Logger, message: str, level: int = logging.INFO, **fields) -> None:
    """Log a message with structured fields attached."""
    logger.log(level, message, extra=fields)


def log_retrieval(
    question: str,
    rewritten: str,
    matches: list[dict],
    latency_ms: float,
    used_cache: bool = False,
    reranked: bool = False,
) -> None:
    """
    Record what retrieval actually returned.

    This is the log that makes bad answers diagnosable: the question, its rewrite,
    the documents and scores that were used, and how long it took.
    """
    log_event(
        _REQUEST_LOGGER,
        "retrieval",
        question=question,
        rewritten=rewritten,
        used_cache=used_cache,
        reranked=reranked,
        latency_ms=round(latency_ms, 1),
        documents=[
            {
                "doc_id": (match.get("metadata") or {}).get("doc_id"),
                "score": round(float(match.get("score") or 0.0), 4),
            }
            for match in matches[:10]
        ],
    )


def log_answer(
    question: str,
    answer: str,
    latency_ms: float,
    grounded: bool,
    source_count: int,
    request_id: str = "",
) -> None:
    """Record what was answered, and whether it cited its sources."""
    log_event(
        _REQUEST_LOGGER,
        "answer",
        request_id=request_id,
        question=question,
        grounded=grounded,
        sources=source_count,
        latency_ms=round(latency_ms, 1),
        answer_chars=len(answer or ""),
        not_found=("could not find" in (answer or "").lower()),
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, time the request, and log one line per request."""

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.time()

        try:
            response = await call_next(request)
        except Exception:
            log_event(
                _REQUEST_LOGGER,
                "request_failed",
                level=logging.ERROR,
                request_id=request_id,
                path=request.url.path,
                method=request.method,
                latency_ms=round((time.time() - started) * 1000, 1),
            )
            raise

        duration_ms = round((time.time() - started) * 1000, 1)
        response.headers["X-Request-ID"] = request_id

        if LOG_REQUESTS and request.url.path not in ("/health", "/health/ready"):
            log_event(
                _REQUEST_LOGGER,
                "request",
                request_id=request_id,
                path=request.url.path,
                method=request.method,
                status=response.status_code,
                latency_ms=duration_ms,
            )

        return response
