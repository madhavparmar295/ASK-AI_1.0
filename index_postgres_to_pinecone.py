"""
Batch Indexer: Sync Unindexed PostgreSQL Documents to Pinecone.
Reads records where pinecone_indexed = FALSE, generates contextual chunks,
batches embeddings via Pinecone Inference with rate-limit protection,
upserts to the 'ask-ai' index, and marks pinecone_indexed = TRUE in PostgreSQL.
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

load_dotenv(override=True)

from services.chunking import chunk_record
from services.document_loader import load_document
from services.embeddings import embed_chunks
from services.pii import apply_pii_protection
from services.postgres import get_conn, row_to_record
from services.vectorstore import get_index, upsert_chunks

BATCH_CHUNK_LIMIT = 32
MAX_CHUNKS_PER_DOC = 50  # Cap huge spreadsheet files (e.g. 1400-chunk mess bills)


def fetch_unindexed_batch(limit: int = 200, source_type: str | None = None) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if source_type:
                cur.execute(
                    """
                    SELECT doc_id, filename, source, source_type, access_level,
                           sender, subject, date, uploaded_at, content, attachment_path
                    FROM documents
                    WHERE pinecone_indexed = FALSE AND source_type = %s
                    ORDER BY uploaded_at DESC NULLS LAST
                    LIMIT %s;
                    """,
                    (source_type, limit),
                )
            else:
                # Order emails first so all club announcements, coordinators, notices index first
                cur.execute(
                    """
                    SELECT doc_id, filename, source, source_type, access_level,
                           sender, subject, date, uploaded_at, content, attachment_path
                    FROM documents
                    WHERE pinecone_indexed = FALSE
                    ORDER BY (CASE WHEN source_type = 'email' THEN 0 ELSE 1 END),
                             uploaded_at DESC NULLS LAST
                    LIMIT %s;
                    """,
                    (limit,),
                )
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]


def mark_batch_indexed(doc_ids: list[str]) -> None:
    if not doc_ids:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET pinecone_indexed = TRUE WHERE doc_id = ANY(%s);",
                (doc_ids,),
            )


def process_document_to_chunks(doc: dict) -> tuple[str, list[dict]]:
    record = row_to_record(doc)
    doc_id = record["doc_id"]

    # Load text from attachment file if content is empty or attachment exists
    if record.get("attachment_path"):
        try:
            loaded_text = load_document(record["attachment_path"])
            if loaded_text and loaded_text.strip():
                protected_text = apply_pii_protection(loaded_text)
                header_parts = []
                sender = record.get("sender")
                subject = record.get("subject")
                date = record.get("date")
                filename = record.get("filename")
                if sender:
                    header_parts.append(f"From: {sender}")
                if subject:
                    header_parts.append(f"Subject: {subject}")
                if date:
                    header_parts.append(f"Date: {date}")
                if filename:
                    header_parts.append(f"File: {filename}")
                prefix = f"[{' | '.join(header_parts)}]\n" if header_parts else ""
                record["text"] = prefix + protected_text
        except Exception:
            if not record.get("text"):
                record["text"] = ""
    elif not record.get("text"):
        record["text"] = ""

    text = record.get("text", "").strip()
    if not text:
        return doc_id, []

    # Defaults come from CHUNK_SIZE_CHARS/CHUNK_OVERLAP_CHARS; the old explicit 500/50
    # window is what left schedule tables and fee lists split across chunks.
    chunks = chunk_record(record)
    valid_chunks = [c for c in chunks if c.get("text", "").strip()]

    # Cap abnormally huge documents (e.g. 1400-chunk mess bills)
    if len(valid_chunks) > MAX_CHUNKS_PER_DOC:
        valid_chunks = valid_chunks[:MAX_CHUNKS_PER_DOC]

    return doc_id, valid_chunks


def run_indexing(limit: int | None = None, source_type: str | None = None):
    print("=" * 65, flush=True)
    print("[*] ASK-AI PostgreSQL -> Pinecone Sync Indexer", flush=True)
    print("=" * 65, flush=True)

    with get_conn() as conn:
        with conn.cursor() as cur:
            if source_type:
                cur.execute("SELECT count(*) FROM documents WHERE pinecone_indexed = FALSE AND source_type = %s;", (source_type,))
            else:
                cur.execute("SELECT count(*) FROM documents WHERE pinecone_indexed = FALSE;")
            total_unindexed = cur.fetchone()[0]

    filter_str = f" [filter: {source_type}]" if source_type else ""
    print(f"[*] Unindexed documents in PostgreSQL{filter_str}: {total_unindexed}", flush=True)
    if total_unindexed == 0:
        print("[*] All matching documents are already indexed in Pinecone! Nothing to do.", flush=True)
        return

    idx = get_index()
    stats = idx.describe_index_stats()
    print(f"[*] Pinecone Index: '{os.getenv('PINECONE_INDEX_NAME', 'ask-ai')}' (current vectors: {stats.total_vector_count})", flush=True)

    target_total = min(total_unindexed, limit) if limit else total_unindexed
    print(f"[*] Target documents for this run: {target_total}", flush=True)
    print("-" * 65, flush=True)

    processed_docs = 0
    total_chunks_indexed = 0
    start_time = time.time()

    while processed_docs < target_total:
        fetch_size = min(200, target_total - processed_docs)
        docs = fetch_unindexed_batch(limit=fetch_size, source_type=source_type)
        if not docs:
            break

        pending_chunks = []
        pending_doc_ids_for_batch = []
        empty_doc_ids = []

        for doc in docs:
            doc_id, chunks = process_document_to_chunks(doc)
            if not chunks:
                empty_doc_ids.append(doc_id)
            else:
                pending_chunks.extend(chunks)
                pending_doc_ids_for_batch.append(doc_id)

            # Flush when chunk queue reaches BATCH_CHUNK_LIMIT
            if len(pending_chunks) >= BATCH_CHUNK_LIMIT:
                _flush_chunks(pending_chunks, pending_doc_ids_for_batch)
                total_chunks_indexed += len(pending_chunks)
                pending_chunks = []
                pending_doc_ids_for_batch = []

        # Flush any remaining chunks in this batch of docs
        if pending_chunks:
            _flush_chunks(pending_chunks, pending_doc_ids_for_batch)
            total_chunks_indexed += len(pending_chunks)
            pending_chunks = []
            pending_doc_ids_for_batch = []

        # Mark empty docs as indexed so they aren't fetched repeatedly
        if empty_doc_ids:
            mark_batch_indexed(empty_doc_ids)

        processed_docs += len(docs)
        elapsed = time.time() - start_time
        speed = processed_docs / elapsed if elapsed > 0 else 0
        pct = (processed_docs / target_total) * 100
        print(f"[{processed_docs}/{target_total} ({pct:.1f}%)] Indexed {total_chunks_indexed} chunks | {speed:.1f} docs/sec", flush=True)

    print("\n" + "=" * 65, flush=True)
    print("Summary:", flush=True)
    print(f" - Documents processed: {processed_docs}", flush=True)
    print(f" - Total chunks pushed to Pinecone: {total_chunks_indexed}", flush=True)
    print(f" - Total elapsed time: {time.time() - start_time:.1f}s", flush=True)
    print("=" * 65, flush=True)

    # Invalidate cached answers built from the content this run replaced.
    try:
        from services.answer_cache import clear as clear_answer_cache

        cleared = clear_answer_cache()
        print(f" - Cached answers cleared: {cleared}", flush=True)
    except Exception as exc:
        print(f" - Answer cache not cleared ({exc}).", flush=True)


def _flush_chunks(chunks: list[dict], doc_ids: list[str]):
    texts = [c["text"] for c in chunks]
    embeddings = embed_chunks(texts)
    if embeddings:
        upsert_chunks(chunks, embeddings)
    if doc_ids:
        mark_batch_indexed(doc_ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync unindexed Postgres documents to Pinecone.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of documents to index")
    parser.add_argument("--type", type=str, default=None, choices=["email", "email_attachment", "website_pdf", "website"], help="Only index specific source_type")
    args = parser.parse_args()

    run_indexing(limit=args.limit, source_type=args.type)
