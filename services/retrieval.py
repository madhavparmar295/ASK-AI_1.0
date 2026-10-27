"""
Retrieval: hybrid search, rank fusion, reranking, neighbour expansion.

The previous pipeline embedded one rewritten query and took the top matches by
cosine similarity, kept only those above a fixed threshold, and - when nothing
cleared it - answered from the top three regardless of whether they were relevant.
Measured on this corpus, that path returned an irrelevant document for
"vidan savaliya" (the notice says "Vidhan Savaliya") because a correct but
keyword-only name match scored 0.2134 while a plausible-looking but wrong chunk
scored higher, and the pass-through fallback then fed the model the wrong chunk.

What happens now, in order:

    1. Rewrite        - the LLM normaliser fixes ordinary typos (unchanged).
    2. Correct tokens - tokens absent from the corpus are replaced by the nearest
                        corpus term, so misspelled names still match. This is the
                        step no general-purpose spell checker can do, because the
                        dictionary is this installation's own corpus.
    3. Dense search   - vector similarity, over a wide candidate set.
    4. Lexical search - SQLite FTS5 over the same chunks, fused with dense results
                        by reciprocal rank fusion. Exact rare tokens (names, codes,
                        filenames) are what dense search is worst at and FTS is best at.
    5. Rerank         - a cross-encoder scores the fused candidates, which is what
                        allows a relevance decision without a magic threshold.
    6. Expand         - the chunks immediately before and after each selected match.

Every stage is timed and logged, so a wrong answer can be traced to the stage that
produced it instead of being inferred from the final text.
"""

from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv

from services.access_control import allowed_access_levels
from services.embeddings import embed_query
from services.query_rewriter import rewrite_query
from services.rerank import rerank
from services.vectorstore import fetch_neighbours, query_similar

load_dotenv()

_logger = logging.getLogger("askai.retrieval")

TOP_CHUNKS = 15
DENSE_CANDIDATES = int(os.getenv("DENSE_CANDIDATES", "40"))
LEXICAL_CANDIDATES = int(os.getenv("LEXICAL_CANDIDATES", "40"))
FUSION_CANDIDATES = int(os.getenv("FUSION_CANDIDATES", "50"))
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "20"))
NEIGHBOUR_RADIUS = int(os.getenv("NEIGHBOUR_RADIUS", "1"))
MAX_NEIGHBOUR_DOCS = int(os.getenv("MAX_NEIGHBOUR_DOCS", "5"))
MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "25"))
NEIGHBOUR_SCORE_DECAY = float(os.getenv("NEIGHBOUR_SCORE_DECAY", "0.9"))
RRF_K = int(os.getenv("RRF_K", "60"))


def _allowed_levels(user_tag: str | None) -> list[str] | None:
    """Access levels a user may see, always including the general backfill bucket."""
    if not user_tag:
        return None
    levels = allowed_access_levels(user_tag)
    if "general" not in levels:
        levels.append("general")
    return levels


def dense_search(query: str, user_tag: str | None, top_k: int = DENSE_CANDIDATES) -> list[dict]:
    """Vector similarity search. Never raises on a transient Pinecone error."""
    try:
        query_embedding = embed_query(query)
        results = query_similar(
            query_embedding=query_embedding,
            user_tag=user_tag,
            top_k=top_k,
            doc_ids=None,
        )
    except Exception as exc:
        _logger.warning("dense search failed: %s", exc)
        return []

    matches = results.get("matches", []) or []
    for match in matches:
        match.setdefault("metadata", {})
        match["source"] = "dense"
    return matches


def lexical_search(query: str, user_tag: str | None, limit: int = LEXICAL_CANDIDATES) -> list[dict]:
    """Keyword search over the FTS5 mirror of the index."""
    try:
        from services import lexical_index

        return lexical_index.search(query, allowed_levels=_allowed_levels(user_tag), limit=limit)
    except Exception as exc:
        _logger.warning("lexical search failed: %s", exc)
        return []


def reciprocal_rank_fusion(rankings: dict[str, list[dict]], k: int = RRF_K) -> list[dict]:
    """
    Fuse ranked lists by reciprocal rank.

    Rank-based fusion needs no score calibration between two rankings that use
    incomparable scales (cosine similarity here, bm25 there), which is why it is the
    standard choice for hybrid search. A chunk found by both retrievers accumulates
    both contributions and rises.

    Each fused candidate keeps the per-retriever ranks and best scores so a bad
    answer can be traced back to which retriever surfaced what.
    """
    fused: dict[str, dict] = {}

    for source, ranking in rankings.items():
        for rank, match in enumerate(ranking, start=1):
            key = match.get("id")
            if not key:
                continue

            entry = fused.setdefault(
                key,
                {
                    "id": key,
                    "score": 0.0,
                    "metadata": match.get("metadata") or {},
                    "sources": {},
                    "retriever_ranks": {},
                },
            )
            entry["score"] += 1.0 / (k + rank)
            entry["retriever_ranks"][source] = rank
            entry["sources"][source] = match.get("score")
            if not entry["metadata"]:
                entry["metadata"] = match.get("metadata") or {}

    ordered = sorted(fused.values(), key=lambda item: item["score"], reverse=True)
    for position, entry in enumerate(ordered, start=1):
        entry["fused_rank"] = position
    return ordered


def expand_matches(
    matches: list[dict],
    radius: int = NEIGHBOUR_RADIUS,
    max_documents: int = MAX_NEIGHBOUR_DOCS,
) -> list[dict]:
    """
    Append the neighbouring chunks of the top documents.

    Neighbours inherit a decayed score from the match that pulled them in and are
    marked as neighbours, so the caller can still tell primary evidence from
    supporting context.
    """
    if radius <= 0 or not matches:
        return []

    seen_documents: list[str] = []
    neighbours: list[dict] = []
    seen_ids = {match.get("id") for match in matches}

    for match in matches:
        metadata = match.get("metadata") or {}
        doc_id = metadata.get("doc_id")
        if not doc_id or doc_id in seen_documents:
            continue

        seen_documents.append(doc_id)
        if len(seen_documents) > max_documents:
            break

        chunk_index = metadata.get("chunk_index")
        if chunk_index is None:
            chunk_index = _chunk_index_from_id(match.get("id"), doc_id)
        if chunk_index is None:
            continue

        try:
            found = fetch_neighbours(doc_id, int(chunk_index), radius=radius)
        except Exception as exc:
            _logger.warning("neighbour expansion failed for %s: %s", doc_id, exc)
            continue

        for neighbour in found:
            if neighbour["id"] in seen_ids:
                continue
            seen_ids.add(neighbour["id"])
            neighbours.append(
                {
                    "id": neighbour["id"],
                    "score": round(float(match.get("score") or 0.0) * NEIGHBOUR_SCORE_DECAY, 6),
                    "metadata": neighbour.get("metadata") or {},
                    "neighbour_of": match.get("id"),
                }
            )

    return neighbours


def _chunk_index_from_id(vector_id: str | None, doc_id: str) -> int | None:
    """Recover the chunk position from an ID shaped ``{doc_id}-{chunk_index}``."""
    if not vector_id or not doc_id:
        return None
    suffix = str(vector_id)[len(str(doc_id)) + 1 :]
    try:
        return int(suffix)
    except ValueError:
        return None


def retrieve_chunks(
    question: str,
    user_tag: str | None = None,
    top_k: int = TOP_CHUNKS,
    session_id: str | None = None,
) -> list[dict]:
    """
    Retrieve the context for a question.

    Returns a ranked list of ``{id, score, metadata}`` chunks. Never raises for a
    retrieval-side failure: a degraded result (dense only, or unreranked) is better
    than a 500 for the user.
    """
    started = time.time()
    timings: dict[str, float] = {}

    # Step 1: LLM rewrite (ordinary typos), then corpus-vocabulary correction on top.
    stage = time.time()
    rewritten = rewrite_query(question)
    timings["rewrite_ms"] = round((time.time() - stage) * 1000, 1)

    stage = time.time()
    search_query, corrections = _correct_query(rewritten)
    timings["correct_ms"] = round((time.time() - stage) * 1000, 1)

    # Step 2: dense and lexical retrieval over the same corpus.
    stage = time.time()
    dense = dense_search(search_query, user_tag=user_tag)
    timings["dense_ms"] = round((time.time() - stage) * 1000, 1)

    stage = time.time()
    lexical = lexical_search(search_query, user_tag=user_tag)
    timings["lexical_ms"] = round((time.time() - stage) * 1000, 1)

    # A query can legitimately contain a token the corpus has never seen; in that case
    # retry keyword search on the corrected form of the original question as well.
    if not lexical and corrections:
        lexical = lexical_search(question, user_tag=user_tag)

    fused = reciprocal_rank_fusion({"dense": dense, "lexical": lexical})
    candidates = fused[:FUSION_CANDIDATES]

    # Step 3: cross-encoder rerank. No threshold and no "top three anyway" fallback:
    # the reranker decides order, and an empty result stays empty.
    stage = time.time()
    ranked, used_reranker = rerank(search_query, candidates, top_n=min(RERANK_TOP_N, max(top_k, 1)))
    timings["rerank_ms"] = round((time.time() - stage) * 1000, 1)

    head = ranked[:top_k]

    # Step 4: expand to neighbouring chunks of the top documents.
    stage = time.time()
    neighbours = expand_matches(head)
    timings["expand_ms"] = round((time.time() - stage) * 1000, 1)

    final: list[dict] = []
    included: set[str] = set()
    for match in head + neighbours:
        if match.get("id") in included:
            continue
        included.add(match.get("id"))
        final.append(match)
    final = final[:MAX_CONTEXT_CHUNKS]

    # Stamp every document that contributed context: retention deletes email chunks
    # that have not been used for a year, so usage has to be recorded on each query.
    try:
        from services.usage import record_usage

        record_usage([match.get("metadata", {}).get("doc_id", "") for match in final])
    except Exception as exc:
        print(f"[Retrieval] Usage tracking skipped: {exc}")

    timings["total_ms"] = round((time.time() - started) * 1000, 1)
    _log_retrieval(
        question=question,
        rewritten=search_query,
        corrections=corrections,
        dense=len(dense),
        lexical=len(lexical),
        fused=len(candidates),
        reranked=used_reranker,
        final=final,
        timings=timings,
        session_id=session_id,
    )

    return final


def _correct_query(query: str) -> tuple[str, dict]:
    """
    Replace query tokens the corpus has never seen with the nearest corpus term.

    This is what rescues a misspelled proper name: the LLM rewriter leaves
    "vidan savaliya" alone (it is not a dictionary word), while this step finds
    "vidhan" in the vocabulary and rewrites the query to match the notice.
    """
    try:
        from services import lexical_index

        return lexical_index.correct_query_tokens(query)
    except Exception as exc:
        _logger.warning("token correction skipped: %s", exc)
        return query, {}


def _log_retrieval(
    question: str,
    rewritten: str,
    corrections: dict,
    dense: int,
    lexical: int,
    fused: int,
    reranked: bool,
    final: list[dict],
    timings: dict,
    session_id: str | None,
) -> None:
    """One structured line per query, with enough detail to debug a bad answer."""
    try:
        from services.logging_config import log_event

        top_documents = []
        for match in final[:10]:
            metadata = match.get("metadata") or {}
            top_documents.append(
                {
                    "doc_id": metadata.get("doc_id"),
                    "chunk_index": metadata.get("chunk_index"),
                    "score": match.get("score"),
                    "neighbour": bool(match.get("neighbour_of")),
                    "retrievers": sorted((match.get("retriever_ranks") or {}).keys()),
                }
            )

        log_event(
            _logger,
            "retrieval",
            level=logging.INFO,
            question=question,
            effective_query=rewritten,
            corrections=corrections or None,
            dense_candidates=dense,
            lexical_candidates=lexical,
            fused_candidates=fused,
            reranked=reranked,
            returned=len(final),
            session_id=session_id,
            documents=top_documents,
            **timings,
        )
    except Exception as exc:  # logging must never break an answer
        _logger.debug("retrieval trace skipped: %s", exc)
