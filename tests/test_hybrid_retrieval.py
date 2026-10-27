"""
Tests for the retrieval rebuild: the lexical index, rank fusion, reranking and
neighbour expansion.

The failures these cover are the ones the old pipeline could not survive:

    * a misspelled proper name that no LLM rewriter corrects but the corpus vocabulary
      can
    * an exact rare token that dense similarity ranks below a plausible-looking
      irrelevant chunk
    * an empty result that the old path silently turned into the top three matches
      anyway, which is what fed the model irrelevant context

No network is involved: dense search, the lexical index, the reranker and the vector
store are all replaced or pointed at temporary storage.
"""

import re

import pytest

from services import index_scan, lexical_index, retrieval
from services import rerank as rerank_module


@pytest.fixture
def keyword_index(tmp_path, monkeypatch):
    """A lexical index in a temporary file, with no leftover connection handle."""
    monkeypatch.setattr(lexical_index, "DB_PATH", str(tmp_path / "lexical.db"))
    monkeypatch.setattr(lexical_index, "LEXICAL_ENABLED", True)
    lexical_index._local.connection = None
    yield lexical_index
    lexical_index._local.connection = None


def chunk(text, doc_id="doc-1", index=0, access_level="public", **extra):
    payload = {
        "text": text,
        "doc_id": doc_id,
        "chunk_index": index,
        "access_level": access_level,
        "source_type": extra.pop("source_type", "email"),
        "sender": extra.pop("sender", ""),
        "subject": extra.pop("subject", ""),
        "filename": extra.pop("filename", ""),
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------- index


def test_index_and_search_roundtrip(keyword_index):
    keyword_index.index_chunks(
        [
            chunk("The coordinator of the E-Cell is Vidhan Savaliya.", doc_id="notice-1", index=0),
            chunk("Mess bill for October is 3200 rupees.", doc_id="mess-1", index=0),
        ]
    )

    matches = keyword_index.search("mess bill", allowed_levels=["public"], limit=5)

    assert len(matches) == 1
    assert matches[0]["metadata"]["doc_id"] == "mess-1"
    assert matches[0]["id"] == "mess-1-0"
    assert matches[0]["source"] == "lexical"
    assert matches[0]["score"] > 0


def test_search_returns_chunk_index_for_neighbour_expansion(keyword_index):
    keyword_index.index_chunks([chunk("Row three of the fee table", doc_id="fees", index=3)])

    matches = keyword_index.search("fee table", allowed_levels=["public"])

    assert matches[0]["metadata"]["chunk_index"] == 3
    assert matches[0]["id"] == "fees-3"


def test_search_respects_access_levels(keyword_index):
    keyword_index.index_chunks(
        [
            chunk("Hostel allotment list for first years", doc_id="restricted", access_level="iitj_restricted"),
            chunk("Hostel allotment policy summary", doc_id="public", access_level="public"),
        ]
    )

    guest_results = keyword_index.search("hostel allotment", allowed_levels=["public"])
    student_results = keyword_index.search("hostel allotment", allowed_levels=["public", "iitj_restricted"])

    assert {match["metadata"]["doc_id"] for match in guest_results} == {"public"}
    assert {match["metadata"]["doc_id"] for match in student_results} == {"public", "restricted"}


def test_reindex_of_a_chunk_replaces_it(keyword_index):
    keyword_index.index_chunks([chunk("Correction: the fee is 1200", doc_id="fees", index=1)])
    keyword_index.index_chunks([chunk("Correction: the fee is 1500", doc_id="fees", index=1)])

    assert keyword_index.stats()["chunks"] == 1
    matches = keyword_index.search("fee", allowed_levels=["public"])
    assert "1500" in matches[0]["metadata"]["text"]


def test_delete_document_removes_every_chunk(keyword_index):
    keyword_index.index_chunks([chunk("a", doc_id="gone", index=0), chunk("b", doc_id="gone", index=1)])

    removed = keyword_index.delete_document("gone")

    assert removed == 2
    assert keyword_index.search("a", allowed_levels=["public"]) == []


def test_match_expression_is_safe_for_punctuation_and_operators(keyword_index):
    """A query is user input: FTS5 syntax characters must not reach MATCH unescaped."""
    hostile = '" OR 1=1 -- ; DROP TABLE chunks; NEAR(/, *'

    expression = lexical_index.match_expression(hostile)

    # Only quoted alphanumeric tokens and OR may survive, so MATCH cannot receive
    # syntax from user input.
    parts = expression.split(" OR ")
    assert parts
    assert all(re.fullmatch(r'"[a-z0-9]+"\*', part) for part in parts)

    keyword_index.index_chunks([chunk("an unrelated memo", doc_id="lib", index=0)])

    # The hostile string matches nothing, and crucially the table is still there.
    assert keyword_index.search(hostile, allowed_levels=["public"]) == []
    assert keyword_index.stats()["chunks"] == 1


def test_empty_query_returns_nothing(keyword_index):
    keyword_index.index_chunks([chunk("some text", doc_id="d", index=0)])
    assert keyword_index.search("", allowed_levels=["public"]) == []


# ------------------------------------------------------------------ token correction


def test_correct_query_rescues_a_misspelled_name(keyword_index):
    keyword_index.index_chunks(
        [chunk("The overall coordinator is Vidhan Savaliya.", doc_id="ecell", index=0)]
    )

    corrected, corrections = keyword_index.correct_query_tokens("vidan savaliya")

    assert "vidhan" in corrected.lower()
    assert corrections == {"vidan": "vidhan"}


def test_correct_query_leaves_unrelated_tokens_alone(keyword_index):
    keyword_index.index_chunks([chunk("The overall coordinator is Vidhan Savaliya.", doc_id="ecell", index=0)])

    corrected, corrections = keyword_index.correct_query_tokens("xqzpta quux")

    assert corrected == "xqzpta quux"
    assert corrections == {}


def test_vocabulary_contains_reports_corpus_membership(keyword_index):
    keyword_index.index_chunks([chunk("Spandan is the annual festival", doc_id="fest", index=0)])

    assert keyword_index.vocabulary_contains("spandan") is True
    assert keyword_index.vocabulary_contains("zzzqqqx") is False


def test_correction_finds_a_prefixed_spelling_without_an_exact_match(keyword_index):
    """A corpus term that only matches after the first character still counts."""
    keyword_index.index_chunks([chunk("Prometeo is the tech fest", doc_id="prometeo", index=0)])

    assert keyword_index.correct_token("prometio") == "prometeo"


# ------------------------------------------------------------------------- fusion


def test_fusion_prefers_a_chunk_found_by_both_retrievers():
    dense = [
        {"id": "a-0", "score": 0.9, "metadata": {"doc_id": "a"}},
        {"id": "b-0", "score": 0.8, "metadata": {"doc_id": "b"}},
    ]
    lexical = [
        {"id": "b-0", "score": 4.0, "metadata": {"doc_id": "b"}},
        {"id": "c-0", "score": 3.0, "metadata": {"doc_id": "c"}},
    ]

    fused = retrieval.reciprocal_rank_fusion({"dense": dense, "lexical": lexical})

    assert fused[0]["id"] == "b-0"
    assert fused[0]["retriever_ranks"] == {"dense": 2, "lexical": 1}
    assert {entry["id"] for entry in fused} == {"a-0", "b-0", "c-0"}
    assert [entry["fused_rank"] for entry in fused] == [1, 2, 3]


def test_fusion_keeps_lexical_only_results():
    fused = retrieval.reciprocal_rank_fusion(
        {"dense": [{"id": "a-0", "score": 0.9, "metadata": {}}], "lexical": [{"id": "z-7", "score": 2.0, "metadata": {}}]}
    )

    assert {entry["id"] for entry in fused} == {"a-0", "z-7"}


def test_fusion_of_empty_lists_is_empty():
    assert retrieval.reciprocal_rank_fusion({"dense": [], "lexical": []}) == []


def test_fusion_skips_matches_without_an_id():
    fused = retrieval.reciprocal_rank_fusion({"dense": [{"score": 0.9, "metadata": {}}]})
    assert fused == []


# ------------------------------------------------------------------------ rerank


class FakeInference:
    def __init__(self, order=None, fail=False):
        self.order = order
        self.fail = fail
        self.calls = 0

    def rerank(self, model, query, documents, rank_fields, top_n, return_documents):
        self.calls += 1
        if self.fail:
            raise RuntimeError("inference unavailable")
        order = self.order if self.order is not None else list(range(len(documents)))
        return type(
            "RerankResult",
            (),
            {"data": [{"index": index, "score": 1.0 - position / 10} for position, index in enumerate(order)]},
        )()


class FakeClient:
    def __init__(self, inference):
        self.inference = inference


def test_rerank_reorders_by_cross_encoder_score(monkeypatch):
    monkeypatch.setattr(rerank_module, "RERANK_ENABLED", True)
    inference = FakeInference(order=[2, 0, 1])
    monkeypatch.setattr("services.embeddings.get_pinecone_client", lambda: FakeClient(inference))

    candidates = [
        {"id": f"d-{i}", "score": 0.5, "metadata": {"text": f"chunk {i}"}} for i in range(3)
    ]

    ranked, used = rerank_module.rerank("a question", candidates)

    assert used is True
    assert [entry["id"] for entry in ranked] == ["d-2", "d-0", "d-1"]
    assert ranked[0]["reranked"] is True
    assert ranked[0]["score"] == 1.0


def test_rerank_keeps_unscored_candidates_after_the_head(monkeypatch):
    monkeypatch.setattr(rerank_module, "RERANK_ENABLED", True)
    monkeypatch.setattr("services.embeddings.get_pinecone_client", lambda: FakeClient(FakeInference(order=[1])))
    monkeypatch.setattr(rerank_module, "RERANK_TOP_N", 1)

    candidates = [{"id": f"d-{i}", "score": 0.5, "metadata": {"text": f"chunk {i}"}} for i in range(3)]

    ranked, used = rerank_module.rerank("a question", candidates, top_n=1)

    assert used is True
    assert ranked[0]["id"] == "d-1"
    assert len(ranked) == 3


def test_rerank_degrades_when_the_service_fails(monkeypatch):
    monkeypatch.setattr(rerank_module, "RERANK_ENABLED", True)
    monkeypatch.setattr("services.embeddings.get_pinecone_client", lambda: FakeClient(FakeInference(fail=True)))

    candidates = [{"id": f"d-{i}", "score": 0.5, "metadata": {"text": f"chunk {i}"}} for i in range(3)]

    ranked, used = rerank_module.rerank("a question", candidates)

    assert used is False
    assert ranked == candidates


def test_rerank_is_skipped_for_a_single_candidate(monkeypatch):
    monkeypatch.setattr(rerank_module, "RERANK_ENABLED", True)
    inference = FakeInference()
    monkeypatch.setattr("services.embeddings.get_pinecone_client", lambda: FakeClient(inference))

    ranked, used = rerank_module.rerank("q", [{"id": "d-0", "score": 1.0, "metadata": {"text": "x"}}])

    assert used is False
    assert inference.calls == 0


# ------------------------------------------------------------------- pipeline


def _match(doc_id, index, score, text="text"):
    return {
        "id": f"{doc_id}-{index}",
        "score": score,
        "metadata": {"doc_id": doc_id, "chunk_index": index, "text": text},
    }


def test_retrieve_chunks_combines_both_retrievers(monkeypatch):
    dense = [_match("dense-only", 0, 0.31), _match("both", 0, 0.29)]
    lexical = [_match("both", 0, 3.1), _match("lexical-only", 0, 2.0)]

    monkeypatch.setattr(retrieval, "rewrite_query", lambda question: question)
    monkeypatch.setattr(retrieval, "_correct_query", lambda query: (query, {}))
    monkeypatch.setattr(retrieval, "dense_search", lambda *a, **k: dense)
    monkeypatch.setattr(retrieval, "lexical_search", lambda *a, **k: lexical)
    monkeypatch.setattr(retrieval, "rerank", lambda query, candidates, top_n=None: (candidates, True))
    monkeypatch.setattr(retrieval, "expand_matches", lambda matches, **k: [])
    monkeypatch.setattr("services.usage.record_usage", lambda doc_ids: 0)

    results = retrieval.retrieve_chunks("who runs the e-cell", user_tag="Student")

    assert [entry["id"] for entry in results] == ["both-0", "dense-only-0", "lexical-only-0"]


def test_retrieve_chunks_returns_nothing_when_retrieval_is_empty(monkeypatch):
    """The old path returned the top three matches even when none were relevant."""
    monkeypatch.setattr(retrieval, "rewrite_query", lambda question: question)
    monkeypatch.setattr(retrieval, "_correct_query", lambda query: (query, {}))
    monkeypatch.setattr(retrieval, "dense_search", lambda *a, **k: [])
    monkeypatch.setattr(retrieval, "lexical_search", lambda *a, **k: [])
    monkeypatch.setattr("services.usage.record_usage", lambda doc_ids: 0)

    assert retrieval.retrieve_chunks("nothing matches this", user_tag="Guest") == []


def test_retrieve_chunks_retries_lexical_search_with_the_original_phrasing(monkeypatch):
    calls = []

    monkeypatch.setattr(retrieval, "rewrite_query", lambda question: "vidhan savaliya")
    monkeypatch.setattr(retrieval, "_correct_query", lambda query: (query, {"vidan": "vidhan"}))
    monkeypatch.setattr(retrieval, "dense_search", lambda *a, **k: [])
    def lexical(query, user_tag, limit=None):
        calls.append(query)
        return [_match("notice", 0, 5.0)] if query == "vidan savaliya" else []

    monkeypatch.setattr(retrieval, "lexical_search", lexical)
    monkeypatch.setattr(retrieval, "rerank", lambda query, candidates, top_n=None: (candidates, False))
    monkeypatch.setattr(retrieval, "expand_matches", lambda matches, **k: [])
    monkeypatch.setattr("services.usage.record_usage", lambda doc_ids: 0)

    results = retrieval.retrieve_chunks("vidan savaliya", user_tag="Student")

    assert calls == ["vidhan savaliya", "vidan savaliya"]
    assert [entry["id"] for entry in results] == ["notice-0"]


def test_expand_matches_adds_neighbours_with_a_decayed_score(monkeypatch):
    monkeypatch.setattr(
        retrieval,
        "fetch_neighbours",
        lambda doc_id, chunk_index, radius=1: [
            {"id": f"{doc_id}-{chunk_index + 1}", "metadata": {"doc_id": doc_id, "chunk_index": chunk_index + 1, "text": "next"}}
        ],
    )

    heads = [_match("fees", 4, 0.8)]
    neighbours = retrieval.expand_matches(heads)

    assert neighbours[0]["id"] == "fees-5"
    assert neighbours[0]["score"] < 0.8
    assert neighbours[0]["neighbour_of"] == "fees-4"


def test_expand_matches_skips_documents_already_seen(monkeypatch):
    calls = []

    def fake_fetch(doc_id, chunk_index, radius=1):
        calls.append(doc_id)
        return []

    monkeypatch.setattr(retrieval, "fetch_neighbours", fake_fetch)

    retrieval.expand_matches([_match("same", 0, 0.9), _match("same", 1, 0.8)])

    assert calls == ["same"]


def test_expand_matches_survives_a_fetch_failure(monkeypatch):
    def boom(doc_id, chunk_index, radius=1):
        raise RuntimeError("pinecone down")

    monkeypatch.setattr(retrieval, "fetch_neighbours", boom)

    assert retrieval.expand_matches([_match("doc", 0, 0.9)]) == []


def test_chunk_index_recovered_from_the_vector_id():
    assert retrieval._chunk_index_from_id("09d74cc7-11", "09d74cc7") == 11
    assert retrieval._chunk_index_from_id("notice-0", "notice") == 0
    assert retrieval._chunk_index_from_id("no-suffix", "no") is None
    assert retrieval._chunk_index_from_id(None, "doc") is None


def test_fetch_batch_recovers_ids_fetch_cannot_return(monkeypatch):
    """
    Fetch returns nothing for an ID containing a space, while a query by ID finds the
    vector. Those chunks exist in the index and must not be silently left out.
    """
    server = {
        "plain-0": {"text": "fetchable"},
        "doc:Patent Form.pdf-0": {"text": "only reachable by query"},
    }
    queried: list[str] = []

    def fake_fetch(ids):
        # The real endpoint answers with whatever subset it can carry.
        return [
            {"id": vector_id, "metadata": server[vector_id]}
            for vector_id in ids
            if index_scan.is_fetchable_id(vector_id)
        ]

    class FakeIndex:
        def query(self, id=None, top_k=None, include_metadata=None):
            queried.append(id)
            metadata = server.get(id)

            class Match:
                pass

            matches = []
            if metadata is not None:
                match = Match()
                match.id = id
                match.metadata = metadata
                matches.append(match)

            class Response:
                pass

            response = Response()
            response.matches = matches
            return response

    monkeypatch.setattr(index_scan, "fetch_vectors", fake_fetch)
    monkeypatch.setattr(index_scan, "get_index", lambda: FakeIndex())

    plain = index_scan.fetch_batch(["plain-0"])
    assert [record["id"] for record in plain] == ["plain-0"]
    assert queried == []  # nothing to recover when fetch worked

    recovered = index_scan.fetch_batch(["plain-0", "doc:Patent Form.pdf-0"], recover_unfetchable=True)
    assert {record["id"] for record in recovered} == {"plain-0", "doc:Patent Form.pdf-0"}
    assert queried == ["doc:Patent Form.pdf-0"]


def test_fetch_batch_without_recovery_leaves_the_gap_and_costs_nothing(monkeypatch):
    monkeypatch.setattr(index_scan, "fetch_vectors", lambda ids: [])

    assert index_scan.fetch_batch(["doc:Patent Form.pdf-0"]) == []


def test_vector_ids_lists_what_is_already_indexed(keyword_index):
    keyword_index.index_chunks([chunk("first", doc_id="a", index=0), chunk("second", doc_id="b", index=1)])

    assert keyword_index.vector_ids() == {"a-0", "b-1"}


def test_rebuild_keeps_legacy_ids_and_counts_unusable_records():
    import rebuild_lexical_index

    chunks, dropped = rebuild_lexical_index._to_chunks(
        [
            {
                # A legacy attachment ID: the chunk position cannot be read from it, and
                # the row must still stand on its own.
                "id": "doc:Patent Form.pdf-7",
                "metadata": {"text": "t", "doc_id": "doc", "access_level": "public"},
            },
            {"id": "doc-1", "metadata": {"doc_id": "doc"}},  # no text
        ]
    )

    assert dropped == 1
    assert chunks[0]["vector_id"] == "doc:Patent Form.pdf-7"
    assert chunks[0]["chunk_index"] == 7


def test_fetchable_ids_are_the_ones_the_fetch_endpoint_carries():
    assert index_scan.is_fetchable_id("09d74cc7-0")
    assert not index_scan.is_fetchable_id("doc:Patent Form.pdf-0")
    assert not index_scan.is_fetchable_id("doc:SOTA+RP.pdf-1")


def test_allowed_levels_always_include_the_general_bucket():
    assert "general" in retrieval._allowed_levels("Student")
    assert retrieval._allowed_levels(None) is None
