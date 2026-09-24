import os

import numpy as np
from services.postgres import DOC_EMBEDDING_DIM

# MiniLM-L6-v2 produces 384-dimensional vectors — used only for
# document-level HNSW search in PostgreSQL, not for Pinecone chunks.
DOC_EMBEDDING_MODEL = os.getenv("DOC_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
_WINDOW_CHARS = 2000
_WINDOW_OVERLAP = 200

_model = None


def get_doc_embedding_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(DOC_EMBEDDING_MODEL)
    return _model


def _windows(text: str) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return [""]
    if len(cleaned) <= _WINDOW_CHARS:
        return [cleaned]

    pieces = []
    start = 0
    step = _WINDOW_CHARS - _WINDOW_OVERLAP
    while start < len(cleaned):
        pieces.append(cleaned[start : start + _WINDOW_CHARS])
        start += step
    return pieces


def _mean_pool(vectors: np.ndarray) -> list[float]:
    mean = vectors.mean(axis=0)
    norm = np.linalg.norm(mean)
    if norm > 0:
        mean = mean / norm
    return mean.astype(float).tolist()


def embed_document(text: str) -> list[float]:
    """Single 384-d vector for a whole document (mean of window embeddings)."""
    model = get_doc_embedding_model()
    vectors = model.encode(_windows(text), normalize_embeddings=True)
    embedding = _mean_pool(np.asarray(vectors))
    if len(embedding) != DOC_EMBEDDING_DIM:
        raise ValueError(f"{DOC_EMBEDDING_MODEL} returned {len(embedding)} dims; " f"expected {DOC_EMBEDDING_DIM}")
    return embedding


def embed_query_384(question: str) -> list[float]:
    model = get_doc_embedding_model()
    vector = model.encode([question], normalize_embeddings=True)[0]
    embedding = np.asarray(vector, dtype=float).tolist()
    if len(embedding) != DOC_EMBEDDING_DIM:
        raise ValueError(f"{DOC_EMBEDDING_MODEL} returned {len(embedding)} dims; " f"expected {DOC_EMBEDDING_DIM}")
    return embedding
