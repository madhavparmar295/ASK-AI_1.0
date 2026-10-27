"""
Chunking for embedding and lexical indexing.

Two changes from the previous fixed 500-character window:

    * Larger, token-budgeted windows. The embedding model (``llama-text-embed-v2``)
      accepts 507 tokens per sequence; 500 characters is roughly 125 tokens, so the
      old setting spent three quarters of the budget and threw away context that
      belongs together - which is why schedule tables and fee structures were split
      mid-row and answered badly.
    * A ``chunk_index`` on every chunk, so retrieval can fetch the chunk immediately
      before and after a match instead of pulling arbitrary chunks from the document.

Sizes are still character-based internally (a fast, dependency-free estimate of
tokens at roughly four characters per token) but both are configurable per call and
by environment.
"""

import math
import os
import re

from dotenv import load_dotenv

load_dotenv()

# ~375 tokens at the usual four-characters-per-token ratio, leaving headroom for the
# document header that is prepended to every chunk.
DEFAULT_CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_CHARS", "1500"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))

# Fraction of the window that must be filled before a sentence/paragraph break is
# allowed to end a chunk early, so we never emit a tiny chunk to honour a break.
MIN_FILL_RATIO = 0.6

_BREAK_RE = re.compile(r"\n\n+|(?<=[.!?;])\s+|\n")


def estimate_tokens(text: str) -> int:
    """Rough token count for a string. Deliberately cheap and dependency-free."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def _soft_end(text: str, start: int, hard_end: int) -> int:
    """
    Prefer ending a chunk at a paragraph or sentence boundary near the hard limit.

    Returns the cut position, or ``hard_end`` when no good break exists.
    """
    if hard_end >= len(text):
        return hard_end

    window = text[start:hard_end]
    minimum = int(len(window) * MIN_FILL_RATIO)

    best = -1
    for match in _BREAK_RE.finditer(window):
        if match.end() >= minimum and match.end() > best:
            best = match.end()

    if best <= 0:
        return hard_end
    return start + best


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """
    Split text into overlapping chunks, cutting at natural boundaries where possible.

    - chunk_size: how many characters each chunk contains
    - overlap: how many characters from the end of one chunk
               are repeated at the start of the next chunk

    Example with chunk_size=1500, overlap=200:
        Chunk 1 -> characters [0:1500]
        Chunk 2 -> characters [1300:2800]   (steps back 200 to preserve context)
        ... and so on until the text runs out.
    """
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    if not text:
        return []

    chunks: list[str] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        hard_end = min(start + chunk_size, text_length)
        end = _soft_end(text, start, hard_end) if hard_end < text_length else hard_end

        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)

        if end >= text_length:
            break

        # Step forward by one window, then back by 'overlap' to preserve context.
        # Measured from the actual end so a soft break keeps the intended overlap,
        # and clamped so the walk always makes progress.
        start = max(end - overlap, start + 1)

    return chunks


def chunk_record(
    record: dict,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict]:
    """
    Takes a record dictionary containing 'text' and returns a list of
    record dictionaries where 'text' is replaced by a chunk of the original text.
    Each chunk preserves the document context header (sender, subject, filename)
    so semantic search matches chunks regardless of position in the document, and
    carries its ``chunk_index`` so retrieval can expand to neighbouring chunks.
    """
    raw_text = record.get("text", "")

    header_prefix = ""
    body_text = raw_text

    # Extract existing header if text was pre-formatted
    if raw_text.startswith("[") and "]\n" in raw_text[:350]:
        parts = raw_text.split("]\n", 1)
        header_prefix = parts[0] + "]\n"
        body_text = parts[1]
    elif record.get("subject") or record.get("filename"):
        subj = record.get("subject") or record.get("filename")
        sndr = record.get("sender")
        if sndr:
            header_prefix = f"[From: {sndr} | Subject: {subj}]\n"
        else:
            header_prefix = f"[{subj}]\n"

    text_chunks = chunk_text(body_text, chunk_size=chunk_size, overlap=overlap)

    chunked_records = []
    for index, chunk in enumerate(text_chunks):
        new_record = record.copy()
        if header_prefix and not chunk.startswith(header_prefix):
            new_record["text"] = header_prefix + chunk
        else:
            new_record["text"] = chunk
        new_record["chunk_index"] = index
        chunked_records.append(new_record)

    return chunked_records
