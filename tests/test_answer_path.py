"""
Tests for the answer path: the shared LLM client, citations and grounding, the answer
cache, conversation memory, and the two ask endpoints.

These cover the failure modes that made the previous handler fragile:

    * one provider error failed the whole question, with no retry and no fallback
    * the same question cost a full retrieval and LLM call every single time
    * a follow-up question had no referent, because no history was passed
    * an uncited answer looked exactly like a cited one
    * nothing stopped one client from spending the shared LLM quota, and the blocking
      calls ran directly in the event loop
"""

import json

import pytest
from fastapi.testclient import TestClient

from services import answer_cache, conversation, llm, rag

PAYLOAD = {"question": "q", "answer": "a"}


# ---------------------------------------------------------------------- LLM client


def fake_provider(result=None, fail_first=0, error=None, stream=None):
    """A provider triple (call, stream, model name) failing the first N calls."""
    state = {"calls": 0}

    def call(messages, temperature, max_tokens):
        state["calls"] += 1
        if state["calls"] <= fail_first:
            raise error or RuntimeError("429 rate limit exceeded")
        return result or "answer text"

    def stream_call(messages, temperature, max_tokens):
        yield from (stream or ["streamed "])

    return (call, stream_call, lambda: "fake-model"), state


@pytest.fixture
def restore_providers(monkeypatch):
    """Provider order and the registry are both patched in-process."""
    original = dict(llm._PROVIDERS)
    monkeypatch.setattr(llm, "available_providers", lambda: ["groq", "ollama"])
    monkeypatch.setattr(llm, "provider_order", lambda: ["groq", "ollama"])
    monkeypatch.setattr(llm, "_PROVIDERS", dict(original))
    llm._cooldown_until.clear()
    yield
    llm._PROVIDERS = original
    llm._cooldown_until.clear()


def test_chat_waits_for_the_delay_the_provider_asked_for(monkeypatch, restore_providers):
    # A rate-limit answer names its own window; sleeping the backoff instead mis-times it.
    slept: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(llm, "available_providers", lambda: ["groq"])
    provider, state = fake_provider(
        result="recovered",
        fail_first=1,
        error=RuntimeError("429 rate limit reached, please try again in 4.2s"),
    )
    monkeypatch.setitem(llm._PROVIDERS, "groq", provider)

    assert llm.chat([{"role": "user", "content": "hi"}]) == "recovered"
    assert state["calls"] == 2
    assert slept == [pytest.approx(4.7)]


def test_chat_does_not_hold_a_request_for_a_longer_wait(monkeypatch, restore_providers):
    # 600s would keep the caller waiting ten minutes; better to fail over now.
    slept: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(llm, "available_providers", lambda: ["groq"])
    provider, state = fake_provider(
        fail_first=99,
        error=RuntimeError("429 rate limit reached, please try again in 600s"),
    )
    monkeypatch.setitem(llm._PROVIDERS, "groq", provider)

    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])

    assert state["calls"] == 1
    assert slept == []


def test_retry_hint_reads_the_retry_after_header_too():
    class Response:
        headers = {"retry-after": "12"}

    class Error(RuntimeError):
        response = Response()

    assert llm._retry_hint(Error("429")) == 12.0
    assert llm._retry_hint(RuntimeError("connection reset")) is None


def test_chat_retries_a_transient_failure(monkeypatch, restore_providers):
    provider, state = fake_provider(result="recovered", fail_first=1)
    monkeypatch.setattr(llm, "available_providers", lambda: ["groq"])
    monkeypatch.setitem(llm._PROVIDERS, "groq", provider)

    assert llm.chat([{"role": "user", "content": "hi"}]) == "recovered"
    assert state["calls"] == 2


def test_chat_falls_back_to_the_next_provider(monkeypatch, restore_providers):
    failing, failing_state = fake_provider(fail_first=99)
    working, working_state = fake_provider(result="from ollama")
    monkeypatch.setitem(llm._PROVIDERS, "groq", failing)
    monkeypatch.setitem(llm._PROVIDERS, "ollama", working)

    assert llm.chat([{"role": "user", "content": "hi"}]) == "from ollama"
    assert failing_state["calls"] == 2  # retried, then gave up on that provider
    assert working_state["calls"] == 1


def test_chat_does_not_retry_a_rejected_key(monkeypatch, restore_providers):
    class Unauthorized(Exception):
        status_code = 401

    failing, failing_state = fake_provider(fail_first=99, error=Unauthorized("invalid api key"))
    working, _ = fake_provider(result="from ollama")
    monkeypatch.setitem(llm._PROVIDERS, "groq", failing)
    monkeypatch.setitem(llm._PROVIDERS, "ollama", working)

    assert llm.chat([{"role": "user", "content": "hi"}]) == "from ollama"
    assert failing_state["calls"] == 1  # a rejected key is not retried


def test_chat_raises_when_every_provider_fails(monkeypatch, restore_providers):
    failing, _ = fake_provider(fail_first=99, error=RuntimeError("500 internal error"))
    monkeypatch.setitem(llm._PROVIDERS, "groq", failing)
    monkeypatch.setitem(llm._PROVIDERS, "ollama", failing)

    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])


def test_chat_raises_when_nothing_is_configured(monkeypatch, restore_providers):
    monkeypatch.setattr(llm, "available_providers", lambda: [])

    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])


def test_chat_stream_falls_back_before_the_first_token(monkeypatch, restore_providers):
    def failing_stream(messages, temperature, max_tokens):
        raise RuntimeError("503 unavailable")
        yield  # pragma: no cover

    working, _ = fake_provider(stream=["hello ", "world"])
    monkeypatch.setitem(llm._PROVIDERS, "groq", (failing_stream, failing_stream, lambda: "m"))
    monkeypatch.setitem(llm._PROVIDERS, "ollama", working)

    assert "".join(llm.chat_stream([{"role": "user", "content": "hi"}])) == "hello world"


def test_chat_stream_does_not_restart_after_partial_output(monkeypatch, restore_providers):
    def partial_stream(messages, temperature, max_tokens):
        yield "half an answer"
        raise RuntimeError("connection reset")

    monkeypatch.setitem(llm._PROVIDERS, "groq", (None, partial_stream, lambda: "m"))
    monkeypatch.setitem(llm._PROVIDERS, "ollama", fake_provider(stream=["other"])[0])

    pieces = []
    with pytest.raises(llm.LLMError):
        for piece in llm.chat_stream([{"role": "user", "content": "hi"}]):
            pieces.append(piece)

    assert pieces == ["half an answer"]


def test_ollama_model_name_is_not_sent_to_groq(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gemma4:e2b")
    assert llm._groq_model() == llm.GROQ_DEFAULT_MODEL


# ------------------------------------------------------------------- rag grounding


def context(text="The mess bill is due on the 10th.", **extra):
    chunk = {
        "text": text,
        "score": 0.7,
        "doc_id": "mess-1",
        "access_level": "public",
        "subject": "October mess bill",
        "sender": "office@iitj.ac.in",
    }
    chunk.update(extra)
    return chunk


def test_extract_citations_ignores_numbers_out_of_range():
    chunks = [context(), context("second")]
    cited = rag.extract_citations("See [Source 1] and [Source 9] and [Source 2].", chunks)
    assert cited == [1, 2]


def test_answer_question_marks_a_cited_answer_as_grounded(monkeypatch):
    monkeypatch.setattr(rag.llm, "chat", lambda *a, **k: "The bill is due on the 10th [Source 1].")

    result = rag.answer_question("when is the bill due", [context()])

    assert result["grounded"] is True
    assert result["cited_sources"] == [1]
    assert result["not_found"] is False


def test_answer_question_marks_an_uncited_answer_as_ungrounded(monkeypatch):
    monkeypatch.setattr(rag.llm, "chat", lambda *a, **k: "The bill is due on the 10th.")

    result = rag.answer_question("when is the bill due", [context()])

    assert result["grounded"] is False
    assert result["cited_sources"] == []


def test_not_found_answer_becomes_the_contact_fallback(monkeypatch):
    monkeypatch.setattr(
        rag.llm,
        "chat",
        lambda *a, **k: "I could not find the answer in the provided documents.",
    )

    result = rag.answer_question("who won the lottery", [context()])

    assert result["not_found"] is True
    assert result["grounded"] is False
    # The bare refusal is replaced by the version that suggests who to contact.
    assert "contact" in result["answer"].lower()


def test_answer_without_context_never_calls_the_model(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("the model must not be called without context")

    monkeypatch.setattr(rag.llm, "chat", explode)

    result = rag.answer_question("anything", [])

    assert result["not_found"] is True
    assert result["answer"]


def test_prompt_includes_recent_history():
    prompt = rag.build_prompt(
        "and the second one?",
        [context()],
        history=[
            {"role": "user", "content": "list the hostel forms"},
            {"role": "assistant", "content": "There are two [Source 1]."},
        ],
    )

    assert "Earlier in this conversation" in prompt
    assert "list the hostel forms" in prompt
    assert "Source 1:" in prompt


def test_prompt_caps_history_length():
    history = [{"role": "user", "content": "x" * 5000}]

    prompt = rag.build_prompt("q", [context()], history=history)

    assert len(prompt) < 6000


def test_stream_answer_yields_fragments(monkeypatch):
    monkeypatch.setattr(rag.llm, "chat_stream", lambda *a, **k: iter(["The bill ", "is due [Source 1]."]))

    assert "".join(rag.stream_answer("q", [context()])) == "The bill is due [Source 1]."


def test_stream_answer_without_context_returns_the_fallback(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("no model call without context")

    monkeypatch.setattr(rag.llm, "chat_stream", explode)

    assert "".join(rag.stream_answer("q", []))


# -------------------------------------------------------------------- answer cache


@pytest.fixture
def clean_cache():
    answer_cache.clear()
    answer_cache._memory.clear()
    yield
    answer_cache.clear()
    answer_cache._memory.clear()


def test_cache_roundtrip_and_miss(clean_cache):
    answer_cache.set("when is the bill due", "Student:iitj.ac.in", PAYLOAD)

    assert answer_cache.get("When is the bill due?", "Student:iitj.ac.in")["answer"] == "a"
    assert answer_cache.get("something else", "Student:iitj.ac.in") is None


def test_cache_never_crosses_access_scopes(clean_cache):
    """The same words from a guest must not return a student's cached answer."""
    answer_cache.set("show the hostel allotment list", "Student:iitj.ac.in", PAYLOAD)

    assert answer_cache.get("show the hostel allotment list", "Guest:gmail.com") is None


def test_cache_expires_entries(clean_cache, monkeypatch):
    answer_cache.set("q", "scope", PAYLOAD)
    monkeypatch.setattr(answer_cache, "TTL_SECONDS", 0)

    assert answer_cache.get("q", "scope") is None


def test_cache_clear_reports_what_it_removed(clean_cache):
    answer_cache.set("q1", "scope", PAYLOAD)
    answer_cache.set("q2", "scope", PAYLOAD)

    assert answer_cache.clear() >= 2
    assert answer_cache.get("q1", "scope") is None


def test_cache_normalisation_is_punctuation_insensitive(clean_cache):
    answer_cache.set("when is the mess bill due?", "scope", PAYLOAD)
    assert answer_cache.get("when is the mess bill due", "scope") is not None


# ------------------------------------------------------------- conversation memory


def test_conversation_records_and_reads_turns(clean_cache):
    conversation.record_turn("s1", "who runs the e-cell", "Vidhan Savaliya [Source 1]")

    history = conversation.get_history("s1")

    assert [turn["role"] for turn in history] == ["user", "assistant"]
    assert history[0]["content"] == "who runs the e-cell"


def test_conversation_trims_old_turns(clean_cache, monkeypatch):
    monkeypatch.setattr(conversation, "TURNS", 2)
    for index in range(5):
        conversation.record_turn("s2", f"question {index}", f"answer {index}")

    history = conversation.get_history("s2")

    assert len(history) == 4
    assert history[0]["content"] == "question 3"


def test_conversation_forgets_a_session(clean_cache):
    conversation.record_turn("s3", "q", "a")
    conversation.forget("s3")

    assert conversation.get_history("s3") == []


def test_conversation_without_a_session_id_is_a_no_op(clean_cache):
    conversation.record_turn(None, "q", "a")
    assert conversation.get_history(None) == []


# ---------------------------------------------------------------------- endpoints


@pytest.fixture(autouse=True)
def fresh_rate_limit_buckets():
    """
    The limiter is keyed by access scope, so every test in this module shares one
    bucket per domain. Clearing it keeps tests independent; the rate-limit test sets
    its own capacity and asserts the 429 itself.
    """
    from services import rate_limiter

    rate_limiter._buckets.clear()
    yield
    rate_limiter._buckets.clear()


@pytest.fixture
def client(monkeypatch):
    from main import app
    from routers import query as query_router

    monkeypatch.setattr(query_router, "retrieve_chunks", lambda *a, **k: [])
    return TestClient(app)


def test_ask_endpoint_returns_citations_and_grounding(client, monkeypatch):
    from routers import query as query_router

    match = {
        "id": "mess-1-0",
        "score": 0.8,
        "metadata": {"doc_id": "mess-1", "chunk_index": 0, "text": "The bill is due on the 10th.", "access_level": "public"},
    }
    monkeypatch.setattr(query_router, "retrieve_chunks", lambda *a, **k: [match])
    monkeypatch.setattr(
        query_router.rag,
        "answer_question",
        lambda question, chunks, history=None: {
            "answer": "Due on the 10th [Source 1].",
            "grounded": True,
            "cited_sources": [1],
            "not_found": False,
            "latency_ms": 12.0,
        },
    )

    response = client.post(
        "/query/ask",
        json={"question": "when is the mess bill due endpoint-1", "user_email": "s1@iitj.ac.in"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["cited_sources"] == [1]
    assert body["sources"][0]["doc_id"] == "mess-1"
    assert response.headers["X-Cache"] == "MISS"


def test_ask_endpoint_serves_the_second_identical_question_from_cache(client, monkeypatch):
    from routers import query as query_router

    calls = {"n": 0}

    def counting_retrieval(*args, **kwargs):
        calls["n"] += 1
        return []

    monkeypatch.setattr(query_router, "retrieve_chunks", counting_retrieval)

    monkeypatch.setattr(
        query_router.rag,
        "answer_question",
        lambda question, chunks, history=None: {
            "answer": "Due on the 10th [Source 1].",
            "grounded": True,
            "cited_sources": [1],
            "not_found": False,
            "latency_ms": 5.0,
        },
    )

    payload = {"question": "cached question endpoint-2", "user_email": "s2@iitj.ac.in"}
    first = client.post("/query/ask", json=payload)
    second = client.post("/query/ask", json=payload)

    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.headers["X-Cache"] == "HIT"
    assert calls["n"] == 1


def test_ask_endpoint_does_not_leak_a_cached_answer_across_scopes(client, monkeypatch):
    from routers import query as query_router

    monkeypatch.setattr(query_router, "retrieve_chunks", lambda *a, **k: [])
    monkeypatch.setattr(
        query_router.rag,
        "answer_question",
        lambda question, chunks, history=None: {
            "answer": "Answer [Source 1].",
            "grounded": True,
            "cited_sources": [1],
            "not_found": False,
            "latency_ms": 5.0,
        },
    )
    question = "scope question endpoint-3"

    client.post("/query/ask", json={"question": question, "user_email": "s3@iitj.ac.in"})
    guest = client.post("/query/ask", json={"question": question, "user_email": "someone@gmail.com"})

    assert guest.json()["cached"] is False


def test_ask_endpoint_rate_limits_one_scope(client, monkeypatch):
    from routers import query as query_router

    monkeypatch.setattr(query_router, "retrieve_chunks", lambda *a, **k: [])
    monkeypatch.setattr(query_router, "ASK_CAPACITY", 2)
    monkeypatch.setattr(query_router, "ASK_REFILL", 0.0)

    payload = {"question": "rate limited question endpoint-4", "user_email": "limited@iitj.ac.in"}
    statuses = [client.post("/query/ask", json=payload).status_code for _ in range(4)]

    assert statuses[:2] == [200, 200]
    assert 429 in statuses[2:]


def test_ask_endpoint_reports_an_llm_outage(client, monkeypatch):
    from routers import query as query_router

    monkeypatch.setattr(query_router, "retrieve_chunks", lambda *a, **k: [{"id": "d-0", "score": 1.0, "metadata": {"doc_id": "d", "text": "t"}}])

    def unavailable(*args, **kwargs):
        raise llm.LLMError("all providers failed")

    monkeypatch.setattr(query_router.rag, "answer_question", unavailable)

    response = client.post(
        "/query/ask",
        json={"question": "outage question endpoint-5", "user_email": "s4@iitj.ac.in"},
    )

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_ask_endpoint_rejects_an_empty_question(client):
    response = client.post("/query/ask", json={"question": "   ", "user_email": "s5@iitj.ac.in"})

    assert response.status_code in (400, 422)


def test_stream_endpoint_sends_sources_tokens_and_done(client, monkeypatch):
    from routers import query as query_router

    match = {
        "id": "d-0",
        "score": 0.9,
        "metadata": {"doc_id": "d", "chunk_index": 0, "text": "text", "access_level": "public"},
    }
    monkeypatch.setattr(query_router, "retrieve_chunks", lambda *a, **k: [match])
    monkeypatch.setattr(query_router.rag, "stream_answer", lambda *a, **k: iter(["The bill ", "is due [Source 1]."]))

    with client.stream(
        "POST",
        "/query/ask/stream",
        json={"question": "streamed question endpoint-6", "user_email": "s6@iitj.ac.in"},
    ) as response:
        assert response.status_code == 200
        events = [
            json.loads(line[len("data: ") :])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]

    kinds = [event["type"] for event in events]
    assert kinds[0] == "sources"
    assert "token" in kinds
    assert kinds[-1] == "done"

    tokens = "".join(event["text"] for event in events if event["type"] == "token")
    assert tokens == "The bill is due [Source 1]."
    assert events[-1]["grounded"] is True
    assert events[-1]["cited_sources"] == [1]


def test_stream_endpoint_reports_a_model_failure_as_an_event(client, monkeypatch):
    from routers import query as query_router

    def failing_stream(*args, **kwargs):
        raise llm.LLMError("provider down")

    monkeypatch.setattr(
        query_router,
        "retrieve_chunks",
        lambda *a, **k: [{"id": "d-0", "score": 1.0, "metadata": {"doc_id": "d", "text": "t"}}],
    )
    monkeypatch.setattr(query_router.rag, "stream_answer", failing_stream)

    with client.stream(
        "POST",
        "/query/ask/stream",
        json={"question": "failing stream question endpoint-7", "user_email": "s7@iitj.ac.in"},
    ) as response:
        events = [
            json.loads(line[len("data: ") :])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]

    assert events[-1]["type"] == "error"


def test_context_is_trimmed_to_the_prompt_budget(monkeypatch):
    monkeypatch.setattr(rag, "MAX_CONTEXT_CHARS", 3000)
    chunks = [
        {"text": "A" * 2000, "doc_id": "first"},
        {"text": "B" * 2000, "doc_id": "second"},
        {"text": "C" * 2000, "doc_id": "third"},
    ]

    kept = rag.fit_context(chunks)

    assert [chunk["doc_id"] for chunk in kept] == ["first"]
    prompt = rag.build_prompt("q", chunks)
    assert "B" * 100 not in prompt


def test_context_budget_keeps_at_least_one_chunk(monkeypatch):
    monkeypatch.setattr(rag, "MAX_CONTEXT_CHARS", 100)

    assert len(rag.fit_context([{"text": "D" * 5000, "doc_id": "huge"}])) == 1


def test_citations_resolve_against_the_trimmed_context(monkeypatch):
    # The model can only cite what it was sent, so a dropped tail must not shift numbers.
    monkeypatch.setattr(rag, "MAX_CONTEXT_CHARS", 2500)
    chunks = [
        {"text": "The coordinator is Vidhan Savaliya.", "doc_id": "first"},
        {"text": "X" * 4000, "doc_id": "second"},
    ]

    def fake_chat(messages, **kwargs):
        assert "X" * 100 not in messages[-1]["content"]
        return "The coordinator is Vidhan Savaliya [Source 1]."

    monkeypatch.setattr(rag.llm, "chat", fake_chat)
    result = rag.answer_question("who is the coordinator", chunks)

    assert result["cited_sources"] == [1]
    assert result["grounded"] is True


def test_cache_stats_endpoint_reports_both_stores(client):
    response = client.get("/query/cache")

    assert response.status_code == 200
    body = response.json()
    assert "answer_cache" in body
    assert body["answer_cache"]["enabled"] is True
