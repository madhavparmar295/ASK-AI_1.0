import os
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2.extras import RealDictCursor

DOC_EMBEDDING_DIM = 384

_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    filename TEXT,
    source TEXT,
    source_type TEXT NOT NULL DEFAULT 'document_upload',
    access_level TEXT NOT NULL DEFAULT 'public',
    sender TEXT,
    subject TEXT,
    date TEXT,
    uploaded_at TIMESTAMPTZ,
    content TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    pinecone_indexed BOOLEAN NOT NULL DEFAULT FALSE,
    attachment_path TEXT
);

-- Add attachment_path to existing tables that were created without it
ALTER TABLE documents ADD COLUMN IF NOT EXISTS attachment_path TEXT;

CREATE INDEX IF NOT EXISTS documents_embedding_hnsw
    ON documents
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS documents_access_level_idx
    ON documents (access_level);
"""


def get_database_url() -> str | None:
    return os.getenv("VECTOR_DB_URL")


@contextmanager
def get_conn():
    url = get_database_url()
    if not url:
        raise RuntimeError(
            "VECTOR_DB_URL (or DATABASE_URL) is not set. " "Point it at a PostgreSQL instance with pgvector."
        )
    conn = psycopg2.connect(url)
    register_vector(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> bool:
    """Create the documents table and HNSW index. Returns False if no DB URL."""
    url = get_database_url()
    if not url:
        return False

    # Create the vector extension first using a raw connection before register_vector is called
    raw_conn = psycopg2.connect(url)
    try:
        with raw_conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        raw_conn.commit()
    finally:
        raw_conn.close()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)
    return True


def upsert_document(record: dict, embedding: list[float]) -> None:
    if len(embedding) != DOC_EMBEDDING_DIM:
        raise ValueError(f"Document embedding must have {DOC_EMBEDDING_DIM} dimensions, " f"got {len(embedding)}")

    uploaded_at = record.get("uploaded_at")
    if isinstance(uploaded_at, str) and uploaded_at:
        uploaded_at_value = uploaded_at
    elif isinstance(uploaded_at, datetime):
        uploaded_at_value = uploaded_at
    else:
        uploaded_at_value = datetime.now(timezone.utc)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (
                    doc_id, filename, source, source_type, access_level,
                    sender, subject, date, uploaded_at, content, embedding,
                    pinecone_indexed, attachment_path
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)
                ON CONFLICT (doc_id) DO UPDATE SET
                    filename = EXCLUDED.filename,
                    source = EXCLUDED.source,
                    source_type = EXCLUDED.source_type,
                    access_level = EXCLUDED.access_level,
                    sender = EXCLUDED.sender,
                    subject = EXCLUDED.subject,
                    date = EXCLUDED.date,
                    uploaded_at = EXCLUDED.uploaded_at,
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    pinecone_indexed = FALSE,
                    attachment_path = EXCLUDED.attachment_path
                """,
                (
                    record["doc_id"],
                    record.get("filename") or record.get("source"),
                    record.get("source"),
                    record.get("source_type") or "document_upload",
                    record.get("access_level") or "public",
                    record.get("sender"),
                    record.get("subject"),
                    record.get("date"),
                    uploaded_at_value,
                    record.get("text") or "",
                    embedding,
                    record.get("attachment_path"),
                ),
            )


def search_documents(
    query_embedding: list[float],
    allowed_levels: list[str] | None = None,
    top_k: int = 2,
) -> list[dict]:
    """HNSW cosine search. `<=>` is cosine distance; similarity is 1 - distance."""
    if len(query_embedding) != DOC_EMBEDDING_DIM:
        raise ValueError(f"Query embedding must have {DOC_EMBEDDING_DIM} dimensions, " f"got {len(query_embedding)}")

    where = ""
    params: list = [query_embedding]
    if allowed_levels:
        where = "WHERE access_level = ANY(%s)"
        params.append(allowed_levels)

    params.extend([query_embedding, top_k])

    # ADDED ::vector to both %s placeholders that handle embeddings
    sql = f"""
        SELECT
            doc_id,
            filename,
            source,
            source_type,
            access_level,
            sender,
            subject,
            date,
            uploaded_at,
            content,
            pinecone_indexed,
            attachment_path,
            1 - (embedding <=> %s::vector) AS score
        FROM documents
        {where}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def mark_pinecone_indexed(doc_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET pinecone_indexed = TRUE WHERE doc_id = %s",
                (doc_id,),
            )


def row_to_record(row: dict) -> dict:
    uploaded_at = row.get("uploaded_at")
    if isinstance(uploaded_at, datetime):
        uploaded_at = uploaded_at.isoformat()

    return {
        "text": row.get("content") or "",
        "doc_id": row["doc_id"],
        "filename": row.get("filename") or row.get("source") or "",
        "source": row.get("source") or "",
        "source_type": row.get("source_type") or "unknown",
        "access_level": row.get("access_level") or "public",
        "sender": row.get("sender") or "",
        "subject": row.get("subject") or "",
        "date": row.get("date") or "",
        "uploaded_at": uploaded_at,
        "attachment_path": row.get("attachment_path"),
    }


def get_document_by_id(doc_id: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    doc_id, filename, source, source_type, access_level,
                    sender, subject, date, uploaded_at, content,
                    pinecone_indexed, attachment_path
                FROM documents
                WHERE doc_id = %s
                """,
                (doc_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_attachments_for_message(message_id: str) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    doc_id, filename, source, source_type, access_level,
                    sender, subject, date, uploaded_at, content,
                    pinecone_indexed, attachment_path
                FROM documents
                WHERE doc_id LIKE %s OR (source_type = 'email_attachment' AND sender = (SELECT sender FROM documents WHERE doc_id = %s) AND subject = (SELECT subject FROM documents WHERE doc_id = %s))
                """,
                (f"{message_id}:%", message_id, message_id),
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]

