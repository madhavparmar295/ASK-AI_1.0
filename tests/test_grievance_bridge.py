"""The two seams between the chatbot and the grievance system.

The grievance API is mounted in the chatbot's application (grievance_app/api.py) and the
grievance form asks this API for a hint (routers/grievance_bridge.py). These tests cover
the seams, not the grievance domain: its own 267 tests live in tests/grievance/.
"""

import time

import pytest
from fastapi.testclient import TestClient

import main
from routers import grievance_bridge

EMPTY = {"answer": "", "sources": []}


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as test_client:
        yield test_client


def _no_flags(text: str) -> dict:
    return {"confidential": False, "urgent": False}


def test_grievance_api_is_mounted_in_the_chatbot_app(client):
    response = client.get("/api/grievance/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_grievance_routes_keep_their_own_sign_in(client):
    """The two services share a process and an origin, not a session."""
    assert client.get("/api/grievance/me").status_code == 401


def test_grievance_admin_routes_are_not_public(client):
    # 401 (or 404 for a hidden resource) - never 200 and never a list of students.
    assert client.get("/api/grievance/admin/users").status_code in (401, 404)


def test_hint_ignores_text_too_short_to_understand(client):
    assert client.post("/chat/api/ask", json={"text": "broken"}).json() == EMPTY


def test_hint_refuses_sensitive_text_before_any_retrieval(client, monkeypatch):
    monkeypatch.setattr(grievance_bridge, "grievance_flags", lambda text: {"confidential": True, "urgent": False})
    called = []
    monkeypatch.setattr(grievance_bridge, "_fast_matches", lambda text: called.append(1) or [])

    response = client.post(
        "/chat/api/ask",
        json={"text": "Someone threatened me in the hostel corridor last night"},
    )

    assert response.json() == EMPTY
    assert called == [], "sensitive text must not reach retrieval or a model"


def test_hint_returns_a_grounded_answer_with_its_sources(client, monkeypatch):
    monkeypatch.setattr(grievance_bridge, "grievance_flags", _no_flags)
    asked = []

    def fake_matches(question):
        asked.append(question)
        return [
            {
                "id": "doc-1-0",
                "score": 0.82,
                "metadata": {
                    "text": "Report air-conditioner faults to the hostel caretaker.",
                    "doc_id": "doc-1",
                    "subject": "Hostel Rules",
                    "source": "https://college.edu/hostel-rules.pdf",
                },
            }
        ]

    monkeypatch.setattr(grievance_bridge, "_fast_matches", fake_matches)
    monkeypatch.setattr(
        grievance_bridge.rag,
        "answer_question",
        lambda *a, **k: {
            "answer": "Report it to the hostel caretaker. [Source 1]",
            "grounded": True,
            "cited_sources": [1],
        },
    )

    response = client.post(
        "/chat/api/ask",
        json={"text": "The AC in my room has not worked since Monday morning"},
    )

    assert response.json() == {
        "answer": "Report it to the hostel caretaker. [Source 1]",
        "sources": [{"title": "Hostel Rules", "section": "", "url": "https://college.edu/hostel-rules.pdf"}],
    }
    assert asked == ["The AC in my room has not worked since Monday morning"]


def test_hint_falls_back_to_keyword_search_when_embeddings_are_slow(monkeypatch):
    """A cold embedding service costs relevance, not the whole hint."""
    monkeypatch.setattr(grievance_bridge, "HINT_DENSE_BUDGET_SECONDS", 0.05)
    monkeypatch.setattr(grievance_bridge, "dense_search", lambda *a, **k: time.sleep(0.4) or [])
    hit = {"id": "doc-3-0", "score": 0.5, "metadata": {"text": "keyword hit", "doc_id": "doc-3"}}
    monkeypatch.setattr(grievance_bridge, "lexical_search", lambda *a, **k: [hit])

    started = time.time()
    matches = grievance_bridge._fast_matches("The tap in the washroom has been leaking for days")

    assert [m["id"] for m in matches] == ["doc-3-0"]
    assert time.time() - started < 0.5


def test_hint_returns_nothing_when_the_answer_is_not_grounded(client, monkeypatch):
    monkeypatch.setattr(grievance_bridge, "grievance_flags", _no_flags)
    monkeypatch.setattr(
        grievance_bridge,
        "_fast_matches",
        lambda text: [{"id": "doc-2-0", "score": 0.2, "metadata": {"text": "Unrelated text", "doc_id": "doc-2"}}],
    )
    monkeypatch.setattr(
        grievance_bridge.rag,
        "answer_question",
        lambda *a, **k: {"answer": "I could not find the answer in the provided documents.", "grounded": False, "cited_sources": []},
    )

    response = client.post("/chat/api/ask", json={"text": "What is the fee for a duplicate ID card?"})

    assert response.json() == EMPTY


def test_hint_gives_up_instead_of_holding_the_form(client, monkeypatch):
    monkeypatch.setattr(grievance_bridge, "grievance_flags", _no_flags)
    monkeypatch.setattr(grievance_bridge, "HINT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(grievance_bridge, "_answer", lambda text: time.sleep(0.4) or {"answer": "late", "sources": []})

    started = time.time()
    response = client.post("/chat/api/ask", json={"text": "The tap in the washroom has been leaking for days"})
    elapsed = time.time() - started

    assert response.json() == EMPTY
    assert elapsed < 1.0, "the form must not wait for the full model call"
