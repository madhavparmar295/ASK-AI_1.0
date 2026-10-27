from services.chunking import chunk_record
from services.doc_embeddings import embed_document
from services.embeddings import embed_chunks
from services.pii import apply_pii_protection
from services.postgres import mark_pinecone_indexed, upsert_document
from services.vectorstore import upsert_chunks


def index_record_to_pinecone(record: dict) -> bool:
    """
    Chunk and upsert a record directly into Pinecone. No PostgreSQL involved.

    This is the whole ingestion path for email: Pinecone holds the chunk text and
    all the metadata retrieval needs, so an email never needs a database row.

    Returns True only when chunks were actually embedded and upserted, so callers
    can tell a successful index apart from a skipped or failed one.
    """
    text_to_index = record.get("text") or record.get("embed_text") or ""
    if not text_to_index and record.get("attachment_path"):
        try:
            from services.document_loader import load_document
            text_to_index = load_document(record["attachment_path"])
        except Exception as e:
            print(f"[Ingest] Could not load attachment for Pinecone: {e}")
            text_to_index = ""

    if not text_to_index or not text_to_index.strip():
        return False

    protected_text = apply_pii_protection(text_to_index)
    header_prefix = ""
    sender = record.get("sender")
    subject = record.get("subject")
    date = record.get("date")
    filename = record.get("filename")
    source_type = record.get("source_type")
    if sender or subject or date:
        header_prefix = f"[From: {sender or 'Unknown'} | Subject: {subject or 'No Subject'} | Date: {date or 'N/A'} | Attachment: {filename or 'File'}]\n"
    elif source_type == "website_pdf":
        header_prefix = f"[Source: {record.get('source') or filename} | File: {filename or 'File'}]\n"
    elif filename:
        header_prefix = f"[File: {filename}]\n"

    chunk_source = record.copy()
    chunk_source["text"] = header_prefix + protected_text

    chunks = chunk_record(chunk_source)
    valid_chunks = [c for c in chunks if c.get("text", "").strip()]
    if not valid_chunks:
        return False

    texts = [c["text"] for c in valid_chunks]
    embeddings = embed_chunks(texts)
    if embeddings:
        upsert_chunks(valid_chunks, embeddings)
        return True

    return False


def ingest_record(record: dict) -> bool:
    """
    Store document metadata in PostgreSQL and index chunks to Pinecone.

    Used for manual uploads and website PDFs, which keep their PostgreSQL row and
    the 384-d document vector. Email takes the Pinecone-only path instead.

    Returns True only when the Pinecone upsert succeeded. The email pipeline uses
    that signal to decide whether a content fingerprint counts as indexed.
    """
    embed_text = record.get("embed_text") or record.get("text") or ""
    try:
        embedding = embed_document(embed_text)
        upsert_document(record, embedding)
    except Exception as e:
        print(f"[Ingest] Postgres upsert warning: {e}")

    # Index directly to Pinecone immediately
    try:
        indexed = index_record_to_pinecone(record)
    except Exception as e:
        print(f"[Ingest] Pinecone indexing error: {e}")
        return False

    if indexed:
        try:
            mark_pinecone_indexed(record["doc_id"])
        except Exception:
            pass

    return indexed

