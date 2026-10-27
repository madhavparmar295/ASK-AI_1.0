"""
Lexical (keyword) index for hybrid retrieval.

Dense embeddings handle paraphrase well but fail on rare exact tokens: a
misspelled name, a course code, a club acronym, a filename. Measured on this
corpus, the query "vidan savaliya" scored 0.2134 against the notice that says
"Vidhan Savaliya" and surfaced an unrelated document instead.

This is a SQLite FTS5 index of chunk text, kept in step with Pinecone through
``vectorstore.upsert_chunks``. It provides:

    * keyword search fused with dense search (reciprocal rank fusion)
    * correction of query tokens that appear nowhere in the corpus, using the
      corpus itself as the dictionary - which is what rescues misspelled names,
      since no general-purpose spell checker knows a campus roster

Nothing here needs a new dependency: FTS5 and ``fts5vocab`` ship with SQLite.
"""

import logging
import os
import re
import sqlite3
import threading

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_db_path = os.getenv("LEXICAL_DB_PATH", "lexical_index.db")
DB_PATH = _db_path if os.path.isabs(_db_path) else os.path.join(BASE_DIR, _db_path)
LEXICAL_ENABLED = os.getenv("HYBRID_SEARCH_ENABLED", "true").lower() not in ("0", "false", "no")
MAX_CORRECTIONS = int(os.getenv("LEXICAL_MAX_CORRECTIONS", "3"))
MAX_CORRECTION_DISTANCE = int(os.getenv("LEXICAL_MAX_DISTANCE", "2"))
VOCAB_CANDIDATES = int(os.getenv("LEXICAL_VOCAB_CANDIDATES", "400"))

_logger = logging.getLogger("askai.lexical")

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    text,
    vector_id UNINDEXED,
    doc_id UNINDEXED,
    chunk_index UNINDEXED,
    access_level UNINDEXED,
    source_type UNINDEXED,
    sender,
    subject,
    filename,
    tokenize = "unicode61 remove_diacritics 2"
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vocab USING fts5vocab(chunks, 'row');
"""

# column order of `chunks`, used for bm25 weighting
_BM25_WEIGHTS = "1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.8, 0.4"

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@+-]*")

_local = threading.local()


def _connect() -> sqlite3.Connection:
    """One connection per thread: this is called from request threads and workers."""
    connection = getattr(_local, "connection", None)
    if connection is not None:
        return connection

    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)

    connection = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row

    # This index is derived data - it can always be rebuilt from the vector store - so
    # a schema change drops it rather than running a migration. ``rebuild_lexical_index``
    # repopulates it.
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        connection.executescript(
            "DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS chunks_vocab;"
        )
        connection.executescript(_SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    connection.executescript(_SCHEMA)
    connection.commit()
    _local.connection = connection
    return connection


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text or "")]


def _sanitize(token: str) -> str:
    """FTS5-safe token: keep alphanumerics so it can be quoted in a MATCH query."""
    return re.sub(r"[^a-z0-9]", "", token.lower())


def match_expression(query: str, prefix: bool = True) -> str:
    """
    Build an FTS5 MATCH expression from free text.

    Tokens are OR-ed (any term may match; bm25 ranks the results) and prefixed, so
    a truncated query like "savali" still hits "savaliya".
    """
    seen: list[str] = []
    for token in _tokens(query):
        sanitized = _sanitize(token)
        if len(sanitized) < 2 or sanitized in seen:
            continue
        seen.append(sanitized)

    if not seen:
        return ""

    clauses = [f'"{token}"*' if prefix else f'"{token}"' for token in seen]
    return " OR ".join(clauses)


def vector_id(doc_id: str, chunk_index: int) -> str:
    """Pinecone ID for a chunk (mirrors the scheme in vectorstore)."""
    return f"{doc_id}-{chunk_index}"


def index_chunks(chunks: list[dict]) -> int:
    """
    Add or replace chunks in the lexical index.

    Called from ``vectorstore.upsert_chunks``, so every chunk that reaches Pinecone
    is also searchable by keyword.
    """
    if not LEXICAL_ENABLED or not chunks:
        return 0

    try:
        connection = _connect()
        cursor = connection.cursor()
        written = 0

        for position, chunk in enumerate(chunks):
            doc_id = str(chunk.get("doc_id") or "")
            if not doc_id:
                continue
            chunk_index = int(chunk.get("chunk_index", position))

            # Keyed by the vector ID, not by (doc_id, chunk_index): some vectors stored
            # before chunk_index existed carry an ID whose doc_id part was ASCII-mangled
            # by the vector store, so the position cannot be recovered, and keying on it
            # would collapse a whole document onto one row and lose its chunks.
            identifier = str(chunk.get("vector_id") or vector_id(doc_id, chunk_index))

            cursor.execute("DELETE FROM chunks WHERE vector_id = ?", (identifier,))
            cursor.execute(
                """
                INSERT INTO chunks
                    (text, vector_id, doc_id, chunk_index, access_level, source_type,
                     sender, subject, filename)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk.get("text") or "",
                    identifier,
                    doc_id,
                    str(chunk_index),
                    chunk.get("access_level") or "public",
                    chunk.get("source_type") or "unknown",
                    chunk.get("sender") or "",
                    chunk.get("subject") or "",
                    chunk.get("filename") or "",
                ),
            )
            written += 1

        connection.commit()
        return written
    except Exception as exc:  # pragma: no cover - depends on the filesystem
        _logger.warning("lexical index write failed: %s", exc)
        return 0


def delete_document(doc_id: str) -> int:
    """Drop every chunk of a document from the lexical index."""
    try:
        connection = _connect()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        connection.commit()
        return cursor.rowcount
    except Exception as exc:  # pragma: no cover
        _logger.warning("lexical index delete failed: %s", exc)
        return 0


def search(query: str, allowed_levels: list[str] | None = None, limit: int = 40) -> list[dict]:
    """
    Keyword search over chunk text and metadata.

    Returns Pinecone-shaped matches so the two ranked lists can be fused directly.
    """
    if not LEXICAL_ENABLED:
        return []

    expression = match_expression(query)
    if not expression:
        return []

    sql = f"""
        SELECT text, vector_id, doc_id, chunk_index, access_level, source_type,
               sender, subject, filename,
               bm25(chunks, {_BM25_WEIGHTS}) AS rank
        FROM chunks
        WHERE chunks MATCH ?
    """
    params: list = [expression]

    if allowed_levels:
        placeholders = ",".join("?" for _ in allowed_levels)
        sql += f" AND access_level IN ({placeholders})"
        params.extend(allowed_levels)

    sql += " ORDER BY rank LIMIT ?"
    params.append(max(1, limit))

    try:
        rows = _connect().execute(sql, params).fetchall()
    except Exception as exc:
        _logger.warning("lexical search failed: %s", exc)
        return []

    matches = []
    for row in rows:
        chunk_index = int(row["chunk_index"] or 0)
        matches.append(
            {
                "id": row["vector_id"] or vector_id(row["doc_id"], chunk_index),
                "score": round(-float(row["rank"]), 6),  # bm25 is negative; higher is better
                "source": "lexical",
                "metadata": {
                    "text": row["text"],
                    "doc_id": row["doc_id"],
                    "chunk_index": chunk_index,
                    "access_level": row["access_level"],
                    "source_type": row["source_type"],
                    "sender": row["sender"],
                    "subject": row["subject"],
                    "filename": row["filename"],
                },
            }
        )
    return matches


def vocabulary_contains(token: str) -> bool:
    """Is this token present anywhere in the corpus?"""
    try:
        row = _connect().execute(
            "SELECT 1 FROM chunks_vocab WHERE term = ? LIMIT 1", (_sanitize(token),)
        ).fetchone()
        return row is not None
    except Exception:
        return True  # never block a query because the vocabulary is unavailable


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Bounded Levenshtein distance: returns limit + 1 as soon as it exceeds it."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    if a == b:
        return 0

    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current.append(
                min(
                    previous[j] + 1,        # deletion
                    current[j - 1] + 1,     # insertion
                    previous[j - 1] + cost,  # substitution
                )
            )
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def correct_token(token: str) -> str | None:
    """
    Find the corpus term closest to an unknown token, if one is close enough.

    Candidates are narrowed by first letter and ordered by how often they occur, so
    a rare misspelling is corrected towards a term the corpus actually uses.
    """
    sanitized = _sanitize(token)
    if len(sanitized) < 4 or vocabulary_contains(sanitized):
        return None

    pattern = f"{sanitized[0]}*"
    try:
        rows = _connect().execute(
            "SELECT term, cnt FROM chunks_vocab WHERE term GLOB ? "
            "ORDER BY cnt DESC LIMIT ?",
            (pattern, VOCAB_CANDIDATES),
        ).fetchall()
    except Exception:
        return None

    best_term, best_distance = None, MAX_CORRECTION_DISTANCE + 1
    for row in rows:
        candidate = row["term"]
        distance = _edit_distance(sanitized, candidate, MAX_CORRECTION_DISTANCE)
        if distance < best_distance and distance <= MAX_CORRECTION_DISTANCE:
            best_term, best_distance = candidate, distance
            if distance == 1:
                break

    return best_term


def correct_query_tokens(query: str, max_corrections: int = MAX_CORRECTIONS) -> tuple[str, dict]:
    """
    Replace query tokens the corpus has never seen with the nearest corpus term.

    Returns the corrected query and the substitutions that were made. Unknown
    tokens are left alone when nothing close enough exists.
    """
    corrections: dict[str, str] = {}
    corrected = query or ""

    for token in _tokens(query):
        if len(corrections) >= max_corrections:
            break
        sanitized = _sanitize(token)
        if len(sanitized) < 4 or sanitized in corrections:
            continue

        replacement = correct_token(sanitized)
        if replacement and replacement != sanitized:
            corrections[sanitized] = replacement
            corrected = re.sub(
                rf"\b{re.escape(token)}\b", replacement, corrected, count=1, flags=re.IGNORECASE
            )

    return corrected, corrections


def vector_ids() -> set[str]:
    """
    Every vector ID already mirrored here.

    The rebuild reads this first so a re-run only fetches what is missing, which makes
    it resumable: an interrupted run continues where it stopped instead of fetching the
    whole corpus again (a fetch of 100 chunks takes seconds, because the response
    carries their text).
    """
    try:
        connection = _connect()
        rows = connection.execute("SELECT vector_id FROM chunks").fetchall()
        return {row[0] for row in rows}
    except Exception as exc:
        _logger.warning("could not read existing vector ids: %s", exc)
        return set()


def stats() -> dict:
    """Row counts for monitoring and the rebuild script."""
    try:
        connection = _connect()
        chunks = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
        terms = connection.execute("SELECT count(*) FROM chunks_vocab").fetchone()[0]
        documents = connection.execute(
            "SELECT count(DISTINCT doc_id) FROM chunks"
        ).fetchone()[0]
        return {
            "enabled": LEXICAL_ENABLED,
            "path": DB_PATH,
            "chunks": chunks,
            "documents": documents,
            "vocabulary_terms": terms,
        }
    except Exception as exc:
        return {"enabled": LEXICAL_ENABLED, "path": DB_PATH, "error": str(exc)}
