import os
import uuid
from unittest.mock import patch

import pytest
from services.postgres import (
    DOC_EMBEDDING_DIM,
    init_db,
    search_documents,
    upsert_document,
)
from services.retrieval import retrieve_chunks

pytestmark = pytest.mark.skipif(
    not (os.getenv("VECTOR_DB_URL") or os.getenv("DATABASE_URL")),
    reason="VECTOR_DB_URL is not set",
)


def _unit_vector(axis: int) -> list[float]:
    vector = [0.0] * DOC_EMBEDDING_DIM
    vector[axis] = 1.0
    return vector


def _record(doc_id: str, text: str, access_level: str = "public") -> dict:
    return {
        "doc_id": doc_id,
        "text": text,
        "filename": f"{doc_id}.txt",
        "source": f"{doc_id}.txt",
        "source_type": "document_upload",
        "access_level": access_level,
    }


def test_hnsw_cosine_returns_nearest_document():
    init_db()
    suffix = uuid.uuid4().hex[:8]
    doc_a = f"exam-calendar-{suffix}"
    doc_b = f"hostel-menu-{suffix}"

    upsert_document(_record(doc_a, "mid semester exam timetable"), _unit_vector(0))
    upsert_document(_record(doc_b, "hostel mess menu for monday"), _unit_vector(1))

    results = search_documents(_unit_vector(0), top_k=2)
    ids = [row["doc_id"] for row in results]
    assert doc_a in ids
    assert ids[0] == doc_a
    assert results[0]["score"] >= results[-1]["score"]


def test_search_respects_access_level():
    init_db()
    suffix = uuid.uuid4().hex[:8]
    public_id = f"public-{suffix}"
    restricted_id = f"restricted-{suffix}"

    upsert_document(_record(public_id, "library hours"), _unit_vector(0))
    upsert_document(
        _record(restricted_id, "student cgpa list", access_level="iitj_restricted"),
        _unit_vector(0),
    )

    results = search_documents(_unit_vector(0), allowed_levels=["public"], top_k=5)
    ids = [row["doc_id"] for row in results]
    assert public_id in ids
    assert restricted_id not in ids


def test_retrieve_chunks_indexes_top_docs_then_queries_pinecone():
    init_db()
    suffix = uuid.uuid4().hex[:8]
    doc_id = f"notice-{suffix}"
    upsert_document(_record(doc_id, "college closed on friday"), _unit_vector(0))

    fake_matches = [
        {
            "id": f"{doc_id}-0",
            "score": 0.9,
            "metadata": {
                "text": "college closed on friday",
                "doc_id": doc_id,
                "access_level": "public",
            },
        }
    ]

    with (
        patch("services.retrieval.embed_query_384", return_value=_unit_vector(0)),
        patch("services.retrieval.embed_chunks", return_value=[[0.0] * 1024]),
        patch("services.retrieval.embed_query", return_value=[0.0] * 1024),
        patch("services.retrieval.upsert_chunks") as upsert,
        patch(
            "services.retrieval.query_similar",
            return_value={"matches": fake_matches},
        ) as pinecone_query,
    ):
        matches = retrieve_chunks("when is college closed?", user_tag="Guest")

    assert matches == fake_matches
    upsert.assert_called_once()
    pinecone_query.assert_called_once()
    kwargs = pinecone_query.call_args.kwargs
    assert kwargs["top_k"] == 5
    assert kwargs["doc_ids"] == [doc_id]
