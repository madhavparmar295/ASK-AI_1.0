import os
import time

from dotenv import load_dotenv

load_dotenv()

# Pinecone client is initialized lazily to avoid import-time failures in CI/tests
_pc = None


def get_pinecone_client():
    """Lazily initialize and return the Pinecone client."""
    global _pc
    if _pc is None:
        from pinecone import Pinecone

        api_key = os.getenv("PINECONE_EMBEDDING_API_KEY") or os.getenv("PINECONE_API_KEY", "fake-key-for-ci")
        _pc = Pinecone(api_key=api_key)
    return _pc


# 1024-d vectors for Pinecone chunk search (after Postgres picks top documents).
# Document-level 384-d vectors live in services/doc_embeddings.py.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "llama-text-embed-v2")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1024"))

# pinecone = hosted inference (default, what the index was built with)
# local    = an on-machine sentence-transformers model, for offline re-indexing and
#            for CI, and to stop large backfills from consuming inference quota
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "pinecone").lower()
LOCAL_EMBEDDING_MODEL = os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")

_local_model = None


def _get_local_model():
    """Load the local model once per process."""
    global _local_model
    if _local_model is not None:
        return _local_model

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "EMBEDDING_BACKEND=local needs sentence-transformers "
            "(pip install sentence-transformers), or set EMBEDDING_BACKEND=pinecone"
        ) from exc

    model = SentenceTransformer(LOCAL_EMBEDDING_MODEL)

    # Vectors from a different model are not comparable with the ones already in the
    # index, and Pinecone rejects a wrong dimension outright, so say so plainly.
    dimension = model.get_sentence_embedding_dimension()
    if dimension != EMBEDDING_DIMENSION:
        raise RuntimeError(
            f"Local model {LOCAL_EMBEDDING_MODEL} produces {dimension}-d vectors but the "
            f"index expects {EMBEDDING_DIMENSION}. Rebuild the index with this backend, "
            "or set EMBEDDING_DIMENSION to match a freshly created index."
        )

    _local_model = model
    return model


def local_embed(texts: list[str]) -> list[list[float]]:
    """Embed with the local model (normalised, matching the hosted model's cosine use)."""
    model = _get_local_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [vector.tolist() for vector in vectors]


def backend() -> str:
    """Which embedding backend is configured, for logs and the readiness report."""
    return EMBEDDING_BACKEND


def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """
    Convert a list of text chunks into a list of embedding vectors.
    input_type='passage' tells the model these are documents being
    stored (as opposed to a search query) — e5-large uses slightly
    different internal handling for each, which improves accuracy.
    """
    if not chunks:
        return []

    if EMBEDDING_BACKEND == "local":
        return local_embed(chunks)

    pc = get_pinecone_client()
    embeddings = []
    batch_size = 32

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        max_retries = 6
        for attempt in range(max_retries):
            try:
                result = pc.inference.embed(
                    model=EMBEDDING_MODEL,
                    inputs=batch,
                    parameters={"input_type": "passage", "truncate": "END"},
                )
                embeddings.extend([item["values"] for item in result])
                time.sleep(0.2)
                break
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "resource_exhausted" in err_str or "rate" in err_str:
                    wait_time = 15 * (attempt + 1)
                    print(f"[*] Pinecone TPM limit reached. Pausing {wait_time}s before retry (attempt {attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    raise e
        else:
            raise RuntimeError(f"Failed to embed batch after {max_retries} retries due to rate limits.")

    return embeddings


def embed_query(question: str) -> list[float]:
    """
    Convert a single question into one embedding vector.
    input_type='query' — must be used at search time so the question
    is embedded the same way queries (not documents) are expected to be.
    """
    if EMBEDDING_BACKEND == "local":
        return local_embed([question])[0]

    pc = get_pinecone_client()
    result = pc.inference.embed(
        model=EMBEDDING_MODEL,
        inputs=[question],
        parameters={"input_type": "query", "truncate": "END"},
    )
    return result[0]["values"]
