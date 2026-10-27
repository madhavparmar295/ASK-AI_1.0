import os
import time
import unicodedata

from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from services.embeddings import EMBEDDING_DIMENSION

load_dotenv()

# Read from env so the same code works locally and on Render
_PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "fake-key-for-ci")
INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ask-ai")

# Fetch sends IDs in the request line, so keep batches well below the URL limit.
FETCH_ID_LIMIT = 200

pc = Pinecone(api_key=_PINECONE_API_KEY)

_index = None


def _to_ascii_id(raw_id: str) -> str:
    """Ensure Pinecone vector ID contains only ASCII characters."""
    # Replace common unicode quotes and dashes with ASCII equivalents
    cleaned = (
        raw_id.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
    )
    # Normalize and strip any other non-ASCII characters
    ascii_id = (
        unicodedata.normalize("NFKD", cleaned)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    if not ascii_id.strip("-"):
        import hashlib
        return hashlib.md5(raw_id.encode("utf-8", "ignore")).hexdigest()
    return ascii_id


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


def vector_id_for(doc_id: str, chunk_index: int) -> str:
    """
    Canonical Pinecone ID for a chunk: ``{doc_id}-{chunk_index}``, ASCII-safe.

    Single source of truth so writer and neighbour-expansion reader agree on the
    scheme. Note ``chunk_index`` is the position within its own document, not within
    an upload batch - callers that batch chunks from several documents must pass the
    per-document index.
    """
    return _to_ascii_id(f"{doc_id}-{int(chunk_index)}")


def upsert_chunks(chunks: list[dict], embeddings: list[list[float]]) -> None:
    """
    Embed-side write path. Also mirrors every chunk into the lexical index, so a
    chunk becomes keyword-searchable the moment it becomes vector-searchable.
    """
    vectors = []
    indexed: list[dict] = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        source_type = chunk.get("source_type", "unknown")
        filename = chunk.get("filename") or chunk.get("source", "")

        # Per-document index, not the batch position: a batch may hold several
        # documents, and the ID is what neighbour expansion reads back later.
        chunk_index = int(chunk.get("chunk_index", i))

        metadata = {
            "text": chunk["text"],
            "access_level": chunk["access_level"],
            "doc_id": chunk["doc_id"],
            "chunk_index": chunk_index,
            "source": chunk.get("source", filename),
            "source_type": source_type,
            "filename": filename,
        }

        if chunk.get("sender"):
            metadata["sender"] = chunk["sender"]
        if chunk.get("subject"):
            metadata["subject"] = chunk["subject"]
        if chunk.get("date"):
            metadata["date"] = chunk["date"]
        if chunk.get("uploaded_at"):
            metadata["uploaded_at"] = chunk["uploaded_at"]

        # When the content entered the index. Retention falls back to this for
        # chunks that have never been retrieved, and `last_used` is stamped here
        # too so every chunk always has a usable timestamp.
        ingested_at = time.time()
        metadata["ingested_at"] = ingested_at
        metadata["last_used"] = ingested_at

        identifier = vector_id_for(chunk["doc_id"], chunk_index)
        vectors.append(
            {
                "id": identifier,
                "values": embedding,
                "metadata": metadata,
            }
        )

        indexed.append(
            {
                "text": metadata["text"],
                "vector_id": identifier,
                "doc_id": chunk["doc_id"],
                "chunk_index": chunk_index,
                "access_level": chunk["access_level"],
                "source_type": source_type,
                "sender": chunk.get("sender") or "",
                "subject": chunk.get("subject") or "",
                "filename": filename,
            }
        )

    if vectors:
        idx = get_index()
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            idx.upsert(vectors=vectors[i : i + batch_size])

    # Lexical mirror. Never fatal: keyword search is an optimisation, and an
    # unwritable index file must not fail ingestion.
    try:
        from services import lexical_index

        lexical_index.index_chunks(indexed)
    except Exception as exc:
        print(f"[VectorStore] Lexical index update skipped: {exc}")


def fetch_neighbours(doc_id: str, chunk_index: int, radius: int = 1) -> list[dict]:
    """
    Fetch the chunks surrounding a match within the same document.

    Replaces the old expansion, which pulled arbitrary chunks of a document via a
    zero-vector query. Reading the immediate neighbours keeps a table or a numbered
    list intact and costs one fetch instead of a full scan of the document.
    """
    if not doc_id:
        return []

    first = max(0, int(chunk_index) - max(0, radius))
    last = int(chunk_index) + max(0, radius)
    ids = [vector_id_for(doc_id, index) for index in range(first, last + 1)]

    neighbours = []
    for vector in fetch_vectors(ids):
        metadata = vector.get("metadata") or {}
        if not metadata.get("text"):
            continue
        neighbours.append({"id": vector["id"], "metadata": metadata})
    return neighbours


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


def touch_documents(doc_ids: list[str], when: float | None = None) -> int:
    """
    Stamp ``last_used`` on every chunk of the given documents.

    Retrieval calls this so the retention task can tell which documents are still
    being asked about. One bulk request per query keeps the write cost flat
    instead of paying Pinecone's per-request minimum for every matched chunk.

    Returns the number of documents stamped (0 when the update failed), and never
    raises: a failed usage stamp must not break answering a question.
    """
    unique = [doc_id for doc_id in dict.fromkeys(doc_ids) if doc_id]
    if not unique:
        return 0

    timestamp = float(when if when is not None else time.time())
    try:
        response = get_index().update(
            filter={"doc_id": {"$in": unique}},
            set_metadata={"last_used": timestamp},
        )
    except Exception as exc:
        print(f"[VectorStore] Could not stamp last_used on {len(unique)} document(s): {exc}")
        return 0

    # The server reports how many records matched. Zero matches means the stamp did
    # not land, which would make live content look abandoned to retention, so make
    # that visible instead of silent.
    matched = getattr(response, "matched_records", None)
    if matched == 0:
        print(
            f"[VectorStore] Warning: last_used stamp matched no vectors for "
            f"{len(unique)} document(s)."
        )

    return matched if matched is not None else len(unique)


def index_size() -> int:
    """Total number of vectors in the index."""
    return int(get_index().describe_index_stats().total_vector_count)


def query_ids_by_filter(filter_dict: dict, limit: int = 1000) -> list[str]:
    """
    List vector IDs matching a metadata filter, without semantic ranking.

    With the cosine metric a zero vector scores every match equally, so this is a
    filtered listing rather than a search. Used by the retention task.
    """
    results = get_index().query(
        vector=[0.0] * EMBEDDING_DIMENSION,
        filter=filter_dict,
        top_k=limit,
        include_metadata=False,
    )
    return [match.id for match in results.matches]


def fetch_vectors(ids: list[str]) -> list[dict]:
    """
    Fetch ``{id, metadata}`` for the given IDs.

    The fetch endpoint carries the IDs in the request line, so a large batch can
    exceed the URL limit (414) long before the documented 1000-ID limit. Batches
    that overflow are split in half and retried.
    """
    if not ids:
        return []

    try:
        response = get_index().fetch(ids=ids[:FETCH_ID_LIMIT])
    except Exception as exc:
        if "414" not in str(exc):
            raise
        if len(ids) == 1:
            print(f"[VectorStore] Skipping vector id that is too long to fetch: {ids[0][:60]}...")
            return []
        middle = len(ids) // 2
        return fetch_vectors(ids[:middle]) + fetch_vectors(ids[middle:])

    vectors = getattr(response, "vectors", None) or {}

    fetched = []
    for vector_id, vector in vectors.items():
        metadata = getattr(vector, "metadata", None)
        if metadata is None and isinstance(vector, dict):
            metadata = vector.get("metadata")
        fetched.append({"id": vector_id, "metadata": metadata or {}})
    return fetched


def delete_vectors(ids: list[str], batch_size: int = 500) -> int:
    """Delete vectors by ID in batches. Returns how many were requested."""
    if not ids:
        return 0

    idx = get_index()
    for start in range(0, len(ids), batch_size):
        idx.delete(ids=ids[start : start + batch_size])
    return len(ids)


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
