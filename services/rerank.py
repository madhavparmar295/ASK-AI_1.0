"""
Cross-encoder reranking of retrieval candidates.

Dense similarity (and rank fusion) orders candidates by proxy signals. A
cross-encoder reads the query and each chunk together and scores actual relevance,
which is what lets the retrieval path drop its fixed similarity threshold and its
"if nothing passes, use the top three anyway" fallback.

Degrades instead of failing: if reranking is disabled, unavailable or errors, the
fused order is returned unchanged and the caller is told it was not reranked.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger("askai.rerank")

RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() not in ("0", "false", "no")
RERANK_MODEL = os.getenv("RERANK_MODEL", "bge-reranker-v2-m3")
RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES", "50"))
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "20"))
MAX_DOCUMENT_CHARS = int(os.getenv("RERANK_MAX_CHARS", "2000"))


def _document_text(candidate: dict) -> str:
    metadata = candidate.get("metadata") or {}
    text = metadata.get("text") or ""
    if not text:
        text = " ".join(
            filter(
                None,
                [
                    metadata.get("subject"),
                    metadata.get("filename"),
                    metadata.get("sender"),
                ],
            )
        )
    return text[:MAX_DOCUMENT_CHARS]


def rerank(query: str, candidates: list[dict], top_n: int | None = None) -> tuple[list[dict], bool]:
    """
    Reorder candidates by cross-encoder relevance.

    Returns (candidates, reranked). The flag is False when the original order was
    kept, so callers and logs can tell the difference.
    """
    if not RERANK_ENABLED or len(candidates) < 2 or not query:
        return candidates, False

    limit = top_n or RERANK_TOP_N
    shortlist = candidates[:RERANK_CANDIDATES]

    documents = [{"id": candidate.get("id") or "", "text": _document_text(candidate)} for candidate in shortlist]
    if not any(document["text"].strip() for document in documents):
        return candidates, False

    try:
        from services.embeddings import get_pinecone_client

        response = get_pinecone_client().inference.rerank(
            model=RERANK_MODEL,
            query=query,
            documents=documents,
            rank_fields=["text"],
            top_n=min(limit, len(documents)),
            return_documents=False,
        )
    except Exception as exc:
        _logger.warning("rerank unavailable, keeping fused order: %s", exc)
        return candidates, False

    scored: list[dict] = []
    for item in getattr(response, "data", []) or []:
        index = item.get("index") if isinstance(item, dict) else getattr(item, "index", None)
        score = item.get("score") if isinstance(item, dict) else getattr(item, "score", None)

        if index is None or index >= len(shortlist):
            continue

        candidate = dict(shortlist[index])
        candidate["score"] = round(float(score if score is not None else 0.0), 6)
        candidate["reranked"] = True
        scored.append(candidate)

    if not scored:
        return candidates, False

    # Anything the reranker did not return follows the reranked head, in fused order.
    returned_ids = {candidate.get("id") for candidate in scored}
    tail = [candidate for candidate in candidates if candidate.get("id") not in returned_ids]

    return scored + tail, True
