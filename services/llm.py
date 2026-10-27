"""
One LLM client for the application.

Before this, ``services/rag.py`` and ``services/query_rewriter.py`` each built their
own client, with no timeout, no retry and no fallback: a single slow or rejected
Groq call surfaced to the user as a failed question, and a provider outage took the
whole product down. Answer generation and query rewriting now share one path with:

    * an explicit per-call timeout, so a hung provider cannot hold a request open
      until the platform kills it
    * retries with exponential backoff and jitter on transient failures
      (429, 5xx, timeouts, connection resets)
    * provider fallback: the configured order is tried in turn, and a provider whose
      credentials are rejected is put in cooldown instead of being retried on every
      single request
    * one structured log line per call, with provider, model, latency and attempts

Configuration::

    LLM_PROVIDER_ORDER=groq,ollama     # default: LLM_PROVIDER first, then the other
    LLM_TIMEOUT_SECONDS=45             # per attempt
    LLM_MAX_ATTEMPTS=3                 # per provider
    LLM_MODEL=openai/gpt-oss-120b      # primary provider's model
    OLLAMA_BASE_URL / OLLAMA_MODEL     # fallback provider
"""

import logging
import os
import random
import re
import time

from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger("askai.llm")

TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
MAX_ATTEMPTS = int(os.getenv("LLM_MAX_ATTEMPTS", "3"))
BACKOFF_BASE_SECONDS = float(os.getenv("LLM_BACKOFF_BASE_SECONDS", "1.5"))
BACKOFF_CAP_SECONDS = float(os.getenv("LLM_BACKOFF_CAP_SECONDS", "20"))
FATAL_COOLDOWN_SECONDS = float(os.getenv("LLM_PROVIDER_COOLDOWN_SECONDS", "120"))
# The longest we will hold a user's request open waiting for a rate-limit window. A
# provider asking for longer than this is skipped instead of slept on. A free provider
# tier answers an answer-sized prompt with "try again in ~30s", so the default has to
# clear that, or every second question in a minute is a failed one.
RETRY_AFTER_MAX_SECONDS = float(os.getenv("LLM_RETRY_AFTER_MAX_SECONDS", "45"))

GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

# Providers whose configuration is rejected stay out of rotation for a while, so a
# dead key costs one attempt instead of one failed attempt per user request.
_cooldown_until: dict[str, float] = {}
_clients: dict[str, object] = {}

TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 524}
FATAL_STATUS = {400, 401, 403, 404, 422}
TRANSIENT_HINTS = (
    "rate limit",
    "too many requests",
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "overloaded",
    "unavailable",
    "try again",
)


class LLMError(RuntimeError):
    """Raised when every configured provider failed to answer."""


def _groq_model() -> str:
    configured = os.getenv("LLM_MODEL", GROQ_DEFAULT_MODEL)
    # A leftover Ollama model name must not be sent to Groq.
    if "gemma" in configured.lower() or "ollama" in configured.lower():
        return GROQ_DEFAULT_MODEL
    return configured


def _ollama_model() -> str:
    configured = os.getenv("OLLAMA_MODEL") or os.getenv("LLM_MODEL") or "llama3.1:8b"
    return configured


def provider_order() -> list[str]:
    """Providers to try, in order."""
    configured = [name.strip().lower() for name in os.getenv("LLM_PROVIDER_ORDER", "").split(",")]
    order = [name for name in configured if name]

    if not order:
        primary = os.getenv("LLM_PROVIDER", "groq").lower()
        primary = "groq" if primary in ("groq", "grok") else "ollama"
        order = [primary] + [name for name in ("groq", "ollama") if name != primary]

    return [name for name in order if name in ("groq", "ollama")]


def available_providers() -> list[str]:
    available = []
    for name in provider_order():
        if name == "groq" and (os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")):
            available.append(name)
        elif name == "ollama":
            _ollama_reachable = True  # checked on use, not at import
            if _ollama_reachable:
                available.append(name)
    return available


def _groq_client():
    if "groq" not in _clients:
        from groq import Groq

        api_key = os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set")
        # Retries are handled here, not by the SDK, so backoff and fallback stay visible.
        _clients["groq"] = Groq(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=0)
    return _clients["groq"]


def _classify(error: Exception) -> str:
    """Is this failure worth retrying, or is it a configuration problem?"""
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None

    if status in TRANSIENT_STATUS:
        return "transient"
    if status in FATAL_STATUS:
        return "fatal"

    text = str(error).lower()
    if any(hint in text for hint in TRANSIENT_HINTS):
        return "transient"
    return "fatal"


RETRY_HINT_RE = re.compile(r"try again in\s*([0-9]+(?:\.[0-9]+)?)s?", re.IGNORECASE)


def _retry_hint(error: Exception) -> float | None:
    """
    The wait the provider itself asked for, in seconds, when it states one.

    A rate-limit answer names exactly how long the window needs. A fixed exponential
    backoff either sleeps too little and fails again, or too long and wastes the
    caller's time, so the provider's own number is preferred when it is usable.
    """
    header = None
    response = getattr(error, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None) or {}
        header = headers.get("retry-after") or headers.get("x-ratelimit-reset-tokens")

    match = RETRY_HINT_RE.search(f"{header or ''} {error}")
    if match:
        seconds = float(match.group(1))
    else:
        try:
            seconds = float(str(header or "").strip())
        except ValueError:
            return None
    return seconds if seconds > 0 else None


def _backoff(attempt: int, error: Exception | None = None) -> float | None:
    """
    Seconds to wait before the next attempt, or ``None`` to stop retrying at once.

    ``None`` means the provider asked for longer than we are prepared to hold a user's
    request open, so the caller should move on rather than sleep.
    """
    hint = _retry_hint(error) if error is not None else None
    if hint is not None:
        if hint > RETRY_AFTER_MAX_SECONDS:
            return None
        return hint + 0.5  # slack, so the window has certainly rolled over

    delay = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    return delay * (0.5 + random.random() / 2)  # jitter, so retries do not synchronise


def _call_groq(messages: list[dict], temperature: float, max_tokens: int | None) -> str:
    kwargs = {"model": _groq_model(), "messages": messages, "temperature": temperature}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    response = _groq_client().chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def _call_ollama(messages: list[dict], temperature: float, max_tokens: int | None) -> str:
    import requests

    api_url = OLLAMA_BASE_URL.replace("/v1", "").rstrip("/") + "/api/chat"
    options: dict = {"temperature": temperature}
    if max_tokens:
        options["num_predict"] = max_tokens

    response = requests.post(
        api_url,
        json={"model": _ollama_model(), "messages": messages, "stream": False, "options": options},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("message", {}).get("content", "")


def _call_groq_stream(messages: list[dict], temperature: float, max_tokens: int | None):
    kwargs = {"model": _groq_model(), "messages": messages, "temperature": temperature, "stream": True}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    for chunk in _groq_client().chat.completions.create(**kwargs):
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


def _call_ollama_stream(messages: list[dict], temperature: float, max_tokens: int | None):
    import json

    import requests

    api_url = OLLAMA_BASE_URL.replace("/v1", "").rstrip("/") + "/api/chat"
    options: dict = {"temperature": temperature}
    if max_tokens:
        options["num_predict"] = max_tokens

    with requests.post(
        api_url,
        json={
            "model": _ollama_model(),
            "messages": messages,
            "stream": True,
            "options": options,
        },
        stream=True,
        timeout=TIMEOUT_SECONDS,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            piece = payload.get("message", {}).get("content")
            if piece:
                yield piece


_PROVIDERS = {
    "groq": (_call_groq, _call_groq_stream, _groq_model),
    "ollama": (_call_ollama, _call_ollama_stream, _ollama_model),
}


def chat(
    messages: list[dict],
    temperature: float = 0.0,
    max_tokens: int | None = None,
    purpose: str = "chat",
    attempts: int | None = None,
) -> str:
    """
    Send a chat completion, retrying and falling back.

    Tries each configured provider in turn; within a provider, transient failures are
    retried with backoff. Raises ``LLMError`` when every provider failed, so callers
    can decide what a user should see.
    """
    order = [name for name in available_providers() if _cooldown_until.get(name, 0) <= time.time()]
    if not order:
        # Everything is in cooldown: try anyway rather than refusing to answer, since
        # a recovered provider should not stay blocked by an old failure.
        order = available_providers()

    if not order:
        raise LLMError("No LLM provider is configured (set GROQ_API_KEY or run Ollama)")

    limit = attempts or MAX_ATTEMPTS
    failures: list[str] = []

    for name in order:
        call, _stream_call, model_of = _PROVIDERS[name]

        for attempt in range(1, limit + 1):
            started = time.time()
            try:
                answer = call(messages, temperature, max_tokens)
                _log_call(name, model_of(), purpose, started, attempt, True)
                return answer
            except Exception as exc:
                kind = _classify(exc)
                _log_call(name, model_of(), purpose, started, attempt, False, error=str(exc)[:200])
                failures.append(f"{name}: {exc}")

                if kind == "fatal":
                    _cooldown_until[name] = time.time() + FATAL_COOLDOWN_SECONDS
                    break

                if attempt < limit:
                    delay = _backoff(attempt, exc)
                    if delay is None:
                        # Waiting would hold this request open longer than the answer is
                        # worth; the next provider may be free right now.
                        break
                    time.sleep(delay)
                    continue
                break

    raise LLMError("; ".join(failures) or "LLM call failed")


def chat_stream(
    messages: list[dict],
    temperature: float = 0.0,
    max_tokens: int | None = None,
    purpose: str = "chat",
):
    """
    Stream a chat completion as text fragments.

    Fallback happens only before the first fragment: once tokens have reached the
    user, restarting with another provider would duplicate output.
    """
    order = available_providers()
    if not order:
        raise LLMError("No LLM provider is configured (set GROQ_API_KEY or run Ollama)")

    failures: list[str] = []

    for name in order:
        _call, stream_call, model_of = _PROVIDERS[name]
        started = time.time()
        emitted = False
        try:
            for piece in stream_call(messages, temperature, max_tokens):
                emitted = True
                yield piece
            _log_call(name, model_of(), purpose, started, 1, True, streamed=emitted)
            return
        except Exception as exc:
            _log_call(name, model_of(), purpose, started, 1, False, error=str(exc)[:200])
            failures.append(f"{name}: {exc}")
            if emitted:
                # The user already has part of an answer; do not restart it elsewhere.
                raise LLMError(f"stream interrupted by {name}: {exc}") from exc
            continue

    raise LLMError("; ".join(failures) or "LLM stream failed")


def _log_call(
    provider: str,
    model: str,
    purpose: str,
    started: float,
    attempt: int,
    ok: bool,
    error: str | None = None,
    streamed: bool | None = None,
) -> None:
    try:
        from services.logging_config import log_event

        fields = {
            "provider": provider,
            "model": model,
            "purpose": purpose,
            "attempt": attempt,
            "ok": ok,
            "latency_ms": round((time.time() - started) * 1000, 1),
        }
        if error:
            fields["error"] = error
        if streamed is not None:
            fields["streamed"] = streamed

        log_event(_logger, "llm_call", level=logging.INFO if ok else logging.WARNING, **fields)
    except Exception:
        pass


def health() -> dict:
    """Which providers are configured, for the readiness report."""
    return {
        "order": provider_order(),
        "available": available_providers(),
        "cooldown": {
            name: round(until - time.time(), 1)
            for name, until in _cooldown_until.items()
            if until > time.time()
        },
    }
