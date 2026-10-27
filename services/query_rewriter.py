"""
Query Rewriter & Spell Normalizer.

Fixes typos, spelling mistakes, and colloquial phrasing before vector embedding,
ensuring RAG retrieval matches correct documents regardless of user typing errors.

The rewrite is a best-effort improvement, never a requirement: if the LLM is
unavailable or slow the original question is used unchanged, so a provider outage
cannot stop questions being asked. Corpus-vocabulary correction of proper nouns
happens after this step, in ``services.lexical_index`` - the model knows English
words, not this campus's names.
"""

import logging
import os
from functools import lru_cache

from dotenv import load_dotenv

from services import llm

load_dotenv()

_logger = logging.getLogger("askai.rewriter")

REWRITE_ENABLED = os.getenv("QUERY_REWRITE_ENABLED", "true").lower() not in ("0", "false", "no")
MAX_REWRITE_TOKENS = int(os.getenv("QUERY_REWRITE_MAX_TOKENS", "60"))

SYSTEM_INSTRUCTION = (
    "You are a search query optimizer for an IIT Jodhpur campus AI assistant. "
    "Your job is to: "
    "1. Fix any spelling errors, typos, and phonetic slips (e.g. 'corrdinator' -> 'coordinator', 'schedle' -> 'schedule'). "
    "2. Normalize campus clubs, festivals, and bodies (E-Cell, SWC, SAC, Prometeo, Spandan, etc.). "
    "3. If the query asks for leadership, head, or coordinator of a club/body, broaden the term slightly "
    "(e.g. 'coordinator' -> 'coordinator or overall coordinator'). "
    "Return ONLY the optimized search query text. Do NOT add quotes, markdown, explanations, or punctuation."
)


@lru_cache(maxsize=512)
def _cached_rewrite(query: str) -> str:
    cleaned = query.strip()
    if not cleaned or len(cleaned) < 4:
        return cleaned

    try:
        result = llm.chat(
            [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": cleaned},
            ],
            temperature=0.0,
            max_tokens=MAX_REWRITE_TOKENS,
            purpose="rewrite",
        ).strip()
    except Exception as exc:
        _logger.warning("query rewrite bypassed: %s", exc)
        return cleaned

    # Strip quotes if the model wrapped its output in them.
    for quote in ('"', "'"):
        if result.startswith(quote) and result.endswith(quote) and len(result) > 2:
            result = result[1:-1].strip()
            break

    # A rewrite must not balloon into an answer-length essay, and must not be empty.
    if not result or len(result) > max(200, len(cleaned) * 4):
        return cleaned

    return result


def rewrite_query(question: str) -> str:
    """
    Public entry point. Optimizes user search query for vector retrieval.
    Falls back gracefully to the original question if rewriting encounters an issue.
    """
    if not question or not question.strip():
        return question

    if not REWRITE_ENABLED:
        return question.strip()

    original = question.strip()
    corrected = _cached_rewrite(original)

    if corrected.lower() != original.lower():
        _logger.info("query normalized", extra={"original": original, "rewritten": corrected})

    return corrected
