"""
Batch indexing utility for storage files.
Iterates over all files in storage/, hashes them using SHA-256 to prevent duplicate
work, extracts text via OCR/parsers, chunks them, embeds them, and upserts to Pinecone.
"""

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

# Ensure root workspace is on path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

load_dotenv(override=True)

from services.access_control import classify_access_level
from services.attachment_processor import process_attachment
from services.chunking import chunk_record
from services.embeddings import embed_chunks
from services.pii import apply_pii_protection
from services.vectorstore import get_index, upsert_chunks

HASH_STORE_FILE = os.path.join(BASE_DIR, "indexed_file_hashes.json")

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".xlsx",
    ".xls",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".bmp",
}


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file's raw binary contents."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_hash_registry() -> dict:
    if os.path.exists(HASH_STORE_FILE):
        try:
            with open(HASH_STORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Warning] Failed to read {HASH_STORE_FILE}: {e}. Creating new registry.")
    return {}


def save_hash_registry(registry: dict) -> None:
    temp_file = f"{HASH_STORE_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    os.replace(temp_file, HASH_STORE_FILE)


def clean_display_name(raw_filename: str) -> str:
    """Strip leading UUID from generated filenames if present."""
    base = os.path.basename(raw_filename)
    if len(base) > 37 and base[8] == "-" and base[13] == "-" and base[18] == "-" and base[23] == "-" and base[36] == "_":
        return base[37:]
    return base


def find_storage_files(storage_dir: str, pdf_only: bool = False) -> list[str]:
    valid_files = []
    for root, _, files in os.walk(storage_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if pdf_only:
                if ext == ".pdf":
                    valid_files.append(os.path.join(root, file))
            else:
                if ext in ALLOWED_EXTENSIONS:
                    valid_files.append(os.path.join(root, file))
    return sorted(valid_files)


def load_postgres_attachment_metadata() -> dict:
    """Preload existing metadata (sender, subject, date, doc_id) from Postgres for storage files."""
    meta_map = {}
    try:
        from services.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT attachment_path, filename, sender, subject, date, doc_id, source_type, access_level "
                    "FROM documents WHERE attachment_path IS NOT NULL;"
                )
                for row in cur.fetchall():
                    att_path, fn, sender, subject, date, doc_id, source_type, access_level = row
                    if att_path:
                        # Normalize path and basename for robust lookup
                        norm_path = os.path.normpath(att_path).lower()
                        meta_map[norm_path] = {
                            "filename": fn,
                            "sender": sender,
                            "subject": subject,
                            "date": date,
                            "doc_id": doc_id,
                            "source_type": source_type or "email_attachment",
                            "access_level": access_level or "public",
                        }
                        meta_map[os.path.basename(norm_path)] = meta_map[norm_path]
    except Exception as e:
        print(f"[*] Note: Could not query Postgres for existing metadata ({e}). Using standard file headers.")
    return meta_map


def index_storage(pdf_only: bool = False, limit: int | None = None, dry_run: bool = False):
    print("=" * 65)
    print("🚀 ASK-AI Storage Document Indexer")
    print("=" * 65)

    idx = get_index()
    stats = idx.describe_index_stats()
    print(f"[*] Pinecone Index Connected: '{os.getenv('PINECONE_INDEX_NAME', 'ask-ai')}'")
    print(f"[*] Current Total Vectors in Index: {stats.total_vector_count}")

    hash_registry = load_hash_registry()
    print(f"[*] Loaded Hash Registry: {len(hash_registry)} files previously recorded")

    postgres_meta = load_postgres_attachment_metadata()
    if postgres_meta:
        print(f"[*] Loaded existing metadata for {len(postgres_meta)} attachment records from DB")

    storage_path = os.path.join(BASE_DIR, "storage")
    files_to_process = find_storage_files(storage_path, pdf_only=pdf_only)
    total_files = len(files_to_process)
    print(f"[*] Found {total_files} candidate files in storage/ (PDF only: {pdf_only})")

    if limit:
        files_to_process = files_to_process[:limit]
        print(f"[*] Limiting run to first {len(files_to_process)} files.")

    print("-" * 65)

    indexed_count = 0
    skipped_count = 0
    error_count = 0
    empty_count = 0
    total_chunks_added = 0

    for idx_num, file_path in enumerate(files_to_process, 1):
        filename = os.path.basename(file_path)
        display_name = clean_display_name(filename)
        ext = os.path.splitext(filename)[1].lower().lstrip(".")

        try:
            file_hash = compute_file_hash(file_path)
        except Exception as e:
            print(f"[{idx_num}/{total_files}] ❌ Error reading {display_name}: {e}")
            error_count += 1
            continue

        # Check if already indexed
        if file_hash in hash_registry:
            entry = hash_registry[file_hash]
            status = entry.get("status", "indexed")
            print(f"[{idx_num}/{total_files}] ⏩ [SKIP - HASH MATCH ({status})] {display_name}")
            skipped_count += 1
            continue

        if dry_run:
            print(f"[{idx_num}/{total_files}] 🔍 [DRY RUN - WOULD INDEX] {display_name} ({ext})")
            continue

        print(f"[{idx_num}/{total_files}] ⏳ Extracting & Processing: {display_name} ...", end=" ", flush=True)

        try:
            # Extract text via attachment processor (handles OCR, excel, etc.)
            extracted_text = process_attachment(file_path, ext)
        except Exception as e:
            print(f"❌ [Extraction Failed: {e}]")
            hash_registry[file_hash] = {
                "filename": display_name,
                "status": f"error: {str(e)[:100]}",
                "attempted_at": datetime.now(timezone.utc).isoformat(),
            }
            save_hash_registry(hash_registry)
            error_count += 1
            continue

        if not extracted_text or not extracted_text.strip():
            print("⚠️ [No Text / Empty]")
            hash_registry[file_hash] = {
                "filename": display_name,
                "status": "empty_or_unreadable",
                "attempted_at": datetime.now(timezone.utc).isoformat(),
            }
            save_hash_registry(hash_registry)
            empty_count += 1
            continue

        # Apply PII protection
        protected_text = apply_pii_protection(extracted_text)

        # Check if this file has existing email attachment metadata
        norm_path = os.path.normpath(file_path).lower()
        base_lower = os.path.basename(norm_path)
        known_meta = postgres_meta.get(norm_path) or postgres_meta.get(base_lower)

        if known_meta:
            doc_id = known_meta.get("doc_id") or str(uuid.uuid4())
            sender = known_meta.get("sender")
            subject = known_meta.get("subject")
            date = known_meta.get("date")
            source_type = known_meta.get("source_type") or "email_attachment"
            access_lvl = known_meta.get("access_level") or classify_access_level(protected_text)
            header_prefix = f"[From: {sender or 'Unknown'} | Subject: {subject or 'No Subject'} | Date: {date or 'N/A'} | Attachment: {display_name}]\n"
        else:
            doc_id = str(uuid.uuid4())
            sender = None
            subject = None
            date = None
            source_type = "document_upload"
            access_lvl = classify_access_level(protected_text)
            header_prefix = f"[File: {display_name}]\n"

        record = {
            "text": header_prefix + protected_text,
            "doc_id": doc_id,
            "filename": display_name,
            "source": display_name,
            "source_type": source_type,
            "access_level": access_lvl,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        if sender:
            record["sender"] = sender
        if subject:
            record["subject"] = subject
        if date:
            record["date"] = date

        # Chunk record
        # Defaults from CHUNK_SIZE_CHARS/CHUNK_OVERLAP_CHARS: the old explicit 500/50
        # fixed window spent most of the embedding model's token budget on nothing and
        # split tables and lists mid-row.
        chunks = chunk_record(record)
        valid_chunks = [c for c in chunks if c.get("text", "").strip()]

        if not valid_chunks:
            print("⚠️ [No valid chunks produced]")
            hash_registry[file_hash] = {
                "filename": display_name,
                "status": "empty_chunks",
                "attempted_at": datetime.now(timezone.utc).isoformat(),
            }
            save_hash_registry(hash_registry)
            empty_count += 1
            continue

        # Embed & upsert to Pinecone
        try:
            texts = [c["text"] for c in valid_chunks]
            embeddings = embed_chunks(texts)
            if embeddings:
                upsert_chunks(valid_chunks, embeddings)
                indexed_count += 1
                total_chunks_added += len(valid_chunks)

                # Store hash in registry
                hash_registry[file_hash] = {
                    "filename": display_name,
                    "path": file_path,
                    "status": "indexed",
                    "doc_id": doc_id,
                    "chunk_count": len(valid_chunks),
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                }
                save_hash_registry(hash_registry)
                print(f"✅ [Upserted {len(valid_chunks)} chunks]")
            else:
                print("❌ [Embedding returned empty]")
                error_count += 1
        except Exception as e:
            print(f"❌ [Pinecone Error: {e}]")
            error_count += 1

    print("\n" + "=" * 65)
    print("📊 Indexing Run Summary:")
    print(f" - Total files inspected: {len(files_to_process)}")
    print(f" - Newly indexed files:   {indexed_count}")
    print(f" - Chunks added to Pinecone: {total_chunks_added}")
    print(f" - Skipped (Already Hashed): {skipped_count}")
    print(f" - Empty/Unreadable:      {empty_count}")
    print(f" - Errors:                {error_count}")
    print(f" - Registry updated at:   {HASH_STORE_FILE}")
    print("=" * 65)

    # Invalidate cached answers built from the content this run replaced.
    if not dry_run:
        try:
            from services.answer_cache import clear as clear_answer_cache

            cleared = clear_answer_cache()
            print(f" - Cached answers cleared: {cleared}")
        except Exception as exc:
            print(f" - Answer cache not cleared ({exc}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index storage documents into Pinecone.")
    parser.add_argument("--pdf-only", action="store_true", help="Only process PDF files")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N files")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without upserting")
    args = parser.parse_args()

    index_storage(pdf_only=args.pdf_only, limit=args.limit, dry_run=args.dry_run)
