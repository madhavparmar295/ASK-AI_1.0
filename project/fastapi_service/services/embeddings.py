import os

from dotenv import load_dotenv

load_dotenv()

# Pinecone client is initialized lazily to avoid import-time failures in CI/tests
_pc = None


def get_pinecone_client():
    """Lazily initialize and return the Pinecone client."""
    global _pc
    if _pc is None:
        from pinecone import Pinecone

        _pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY", "fake-key-for-ci"))
    return _pc


# 1024-d vectors for Pinecone chunk search (after Postgres picks top documents).
# Document-level 384-d vectors live in services/doc_embeddings.py.
EMBEDDING_MODEL = "llama-text-embed-v2"
EMBEDDING_DIMENSION = 1024


def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """
    Convert a list of text chunks into a list of embedding vectors.
    input_type='passage' tells the model these are documents being
    stored (as opposed to a search query) — e5-large uses slightly
    different internal handling for each, which improves accuracy.
    """
    if not chunks:
        return []

    pc = get_pinecone_client()
    result = pc.inference.embed(
        model=EMBEDDING_MODEL,
        inputs=chunks,
        parameters={"input_type": "passage", "truncate": "END"},
    )

    # result is a list-like object of embedding records, each with a
    # .values field containing the actual vector
    embeddings = [item["values"] for item in result]
    return embeddings


def embed_query(question: str) -> list[float]:
    """
    Convert a single question into one embedding vector.
    input_type='query' — must be used at search time so the question
    is embedded the same way queries (not documents) are expected to be.
    """
    pc = get_pinecone_client()
    result = pc.inference.embed(
        model=EMBEDDING_MODEL,
        inputs=[question],
        parameters={"input_type": "query", "truncate": "END"},
    )
    return result[0]["values"]
