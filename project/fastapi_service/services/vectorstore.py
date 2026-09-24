import os

from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from services.embeddings import EMBEDDING_DIMENSION

load_dotenv()

# Read from env so the same code works locally and on Render
_PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "fake-key-for-ci")
INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ask-ai")

pc = Pinecone(api_key=_PINECONE_API_KEY)

_index = None


def get_index():
    """Lazily initialize and return the Pinecone index (creates it if missing)."""
    global _index
    if _index is None:
        if not pc.has_index(INDEX_NAME):
            pc.create_index(
                name=INDEX_NAME,
                dimension=EMBEDDING_DIMENSION,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
        _index = pc.Index(INDEX_NAME)
    return _index


def upsert_chunks(chunks: list[dict], embeddings: list[list[float]]) -> None:
    vectors = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        source_type = chunk.get("source_type", "unknown")
        metadata = {
            "text": chunk["text"],
            "access_level": chunk["access_level"],
            "doc_id": chunk["doc_id"],
            "source": chunk["source"],
            "source_type": source_type,
        }

        if source_type == "email":
            metadata["sender"] = chunk.get("sender", "")
            metadata["subject"] = chunk.get("subject", "")
            metadata["date"] = chunk.get("date", "")
            metadata["filename"] = chunk.get("filename", "")
        else:
            metadata["filename"] = chunk.get("filename", "")
            if "uploaded_at" in chunk:
                metadata["uploaded_at"] = chunk["uploaded_at"]

        vectors.append(
            {
                "id": f"{chunk['doc_id']}-{i}",
                "values": embedding,
                "metadata": metadata,
            }
        )
    if vectors:
        get_index().upsert(vectors=vectors)


def query_similar(
    query_embedding: list,
    user_tag: str = None,
    top_k: int = 5,
    doc_ids: list[str] | None = None,
) -> dict:
    """
    Search Pinecone for the most similar chunks.
    Optionally filter by access_level (user_tag) so users only see their org's data.
    Returns a dict with a 'matches' key to match Pinecone's native response shape.
    """
    clauses = []
    if user_tag:
        # pyrefly: ignore [missing-import]
        from services.access_control import allowed_access_levels

        allowed_levels = allowed_access_levels(user_tag)
        # Always include "general" for email backfill chunks
        if "general" not in allowed_levels:
            allowed_levels.append("general")
        clauses.append({"access_level": {"$in": allowed_levels}})
    if doc_ids:
        clauses.append({"doc_id": {"$in": doc_ids}})

    if not clauses:
        filter_dict = None
    elif len(clauses) == 1:
        filter_dict = clauses[0]
    else:
        filter_dict = {"$and": clauses}

    results = get_index().query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,
        filter=filter_dict,
    )

    # Convert Pinecone ScoredVector objects to standard dicts so query.py can use match["metadata"]
    normalized_matches = []
    for m in results.matches:
        normalized_matches.append({"id": m.id, "score": m.score, "metadata": m.metadata})

    return {"matches": normalized_matches}


def semantic_search(query_embedding: list, doc_id: str = None, top_k: int = 3) -> list:
    """Legacy helper used by the document CRUD endpoints."""
    filter_dict = {"doc_id": {"$eq": doc_id}} if doc_id else None
    results = get_index().query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,
        filter=filter_dict,
    )
    return [
        {
            "score": m.score,
            "doc_id": m.metadata.get("doc_id"),
            "chunk_index": m.metadata.get("chunk_index"),
            "text": m.metadata.get("text"),
        }
        for m in results.matches
    ]


def delete_document_vectors(doc_id: str) -> None:
    get_index().delete(filter={"doc_id": {"$eq": doc_id}})
