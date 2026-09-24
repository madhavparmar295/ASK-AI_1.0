from services.access_control import allowed_access_levels
from services.chunking import chunk_record
from services.doc_embeddings import embed_query_384
from services.embeddings import embed_chunks, embed_query
from services.postgres import (
    mark_pinecone_indexed,
    row_to_record,
    search_documents,
)
from services.vectorstore import query_similar, upsert_chunks

TOP_DOCUMENTS = 2
TOP_CHUNKS = 5


def _index_document_chunks(doc: dict) -> None:
    record = row_to_record(doc)
    chunks = chunk_record(record)
    texts = [c["text"] for c in chunks]
    embeddings = embed_chunks(texts)
    upsert_chunks(chunks, embeddings)
    mark_pinecone_indexed(doc["doc_id"])


def retrieve_chunks(question: str, user_tag: str | None = None) -> list[dict]:
    """Two-stage search: Postgres HNSW (top 2 docs) then Pinecone (top 5 chunks)."""
    allowed = None
    if user_tag:
        allowed = allowed_access_levels(user_tag)
        if "general" not in allowed:
            allowed.append("general")

    query_384 = embed_query_384(question)
    documents = search_documents(query_384, allowed_levels=allowed, top_k=TOP_DOCUMENTS)
    if not documents:
        return []

    for doc in documents:
        if not doc.get("pinecone_indexed"):
            _index_document_chunks(doc)

    query_1024 = embed_query(question)
    doc_ids = [doc["doc_id"] for doc in documents]
    results = query_similar(
        query_1024,
        user_tag=user_tag,
        top_k=TOP_CHUNKS,
        doc_ids=doc_ids,
    )
    return results["matches"]
