"""
Build the keyword (FTS5) index from the vectors already in Pinecone.

Hybrid retrieval needs a lexical index over the same chunks the vector store holds.
There is no separate copy of that text: the chunks live in Pinecone metadata, and
Postgres is optional in this deployment, so the rebuild reads the index itself.

    python rebuild_lexical_index.py                  # read only what is missing
    python rebuild_lexical_index.py --rewrite-all    # re-read everything
    python rebuild_lexical_index.py --limit 2000     # sample, for a quick check
    python rebuild_lexical_index.py --reset          # drop existing rows first
    python rebuild_lexical_index.py --dry-run        # report, write nothing
    python rebuild_lexical_index.py --no-recover     # skip the slow query fallback

Run it once after deploying hybrid retrieval, and again whenever content was
ingested while the lexical index was unavailable. Ingestion keeps both in step from
then on.

Note on chunk order: vectors written before ``chunk_index`` existed do not carry it,
so the position is read from the ID (``{doc_id}-{chunk_index}``). That is exactly how
neighbour expansion reads it too.

Note on coverage: the fetch endpoint returns nothing for an ID containing a space or a
plus sign, which is most attachment chunks in this corpus. Those are read back with a
query instead, so the keyword index ends up covering the whole index rather than the
subset fetch happens to be able to return.

Note on re-runs: rows already present are skipped, so an interrupted rebuild resumes
rather than starting over. That matters because a fetch of a hundred chunks takes
seconds - the response carries their text - and the whole corpus is thirty-four
thousand chunks.
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from services import lexical_index  # noqa: E402
from services.index_scan import (  # noqa: E402
    fetch_batch,
    is_fetchable_id,
    iter_vector_ids,
    unrecoverable_ids,
)

BATCH_SIZE = 100


def _chunk_index(vector_id: str, doc_id: str) -> int:
    """
    Chunk position, read from the ID because older metadata has no field for it.

    Current IDs are ``{doc_id}-{position}``. Legacy attachment IDs are
    ``{doc_id}:{filename}-{position}``, where slicing past the doc_id leaves the
    filename in place, so the trailing segment after the last dash is the fallback.
    """
    suffix = str(vector_id)[len(str(doc_id)) + 1 :] if doc_id else ""
    for candidate in (suffix, str(vector_id).rsplit("-", 1)[-1]):
        try:
            return int(candidate)
        except ValueError:
            continue
    return 0


def _to_chunks(records: list[dict]) -> tuple[list[dict], int]:
    """Turn fetched records into index rows, and count the unusable ones."""
    chunks: list[dict] = []
    dropped = 0

    for record in records:
        metadata = record.get("metadata") or {}
        text = metadata.get("text")
        doc_id = metadata.get("doc_id")

        if not text or not doc_id:
            dropped += 1
            continue

        chunk_index = metadata.get("chunk_index")
        if chunk_index is None:
            chunk_index = _chunk_index(record["id"], doc_id)

        chunks.append(
            {
                "text": text,
                # The exact vector ID, so a document whose legacy ID cannot be
                # parsed still keeps every chunk as its own row.
                "vector_id": record["id"],
                "doc_id": doc_id,
                "chunk_index": int(chunk_index),
                "access_level": metadata.get("access_level") or "public",
                "source_type": metadata.get("source_type") or "unknown",
                "sender": metadata.get("sender") or "",
                "subject": metadata.get("subject") or "",
                "filename": metadata.get("filename") or "",
            }
        )

    return chunks, dropped


def rebuild(
    limit: int | None = None,
    reset: bool = False,
    dry_run: bool = False,
    recover_unfetchable: bool = True,
    rewrite_all: bool = False,
) -> dict:
    started = time.time()
    written = 0
    skipped = 0
    batches = 0
    recovered = 0
    already_present = 0
    existing: set[str] = set()

    if reset and not dry_run:
        connection = lexical_index._connect()
        connection.execute("DELETE FROM chunks")
        connection.commit()
        print("[Rebuild] Cleared the existing lexical index.")

    if dry_run:
        print("[Rebuild] Dry run: nothing will be written.")

    if not reset and not rewrite_all:
        existing = lexical_index.vector_ids()
        if existing:
            print(
                f"[Rebuild] {len(existing)} vectors are already indexed; only the rest "
                "will be read."
            )

    def write(records: list[dict]) -> None:
        nonlocal written, skipped, recovered

        recovered += sum(1 for record in records if not is_fetchable_id(record["id"]))
        chunks, dropped = _to_chunks(records)
        skipped += dropped

        written += len(chunks) if dry_run else lexical_index.index_chunks(chunks)

        print(
            f"\r[Rebuild] batches={batches} written={written} recovered={recovered} "
            f"already_present={already_present} skipped={skipped}",
            end="",
            flush=True,
        )

    pending: list[str] = []
    for vector_id in iter_vector_ids(page_size=BATCH_SIZE, limit=limit):
        if vector_id in existing:
            already_present += 1
            continue

        pending.append(vector_id)
        if len(pending) < BATCH_SIZE:
            continue

        batches += 1
        write(fetch_batch(pending, recover_unfetchable=recover_unfetchable))
        pending = []

    if pending:
        # The tail of the listing, once the loop stopped filling whole batches.
        batches += 1
        write(fetch_batch(pending, recover_unfetchable=recover_unfetchable))

    summary = {
        "written": written,
        "skipped": skipped,
        "recovered": recovered,
        "already_present": already_present,
        "unrecoverable": sorted(unrecoverable_ids()),
        "batches": batches,
        "seconds": round(time.time() - started, 1),
        "dry_run": dry_run,
        "index": lexical_index.stats(),
    }

    print()
    print(
        f"[Rebuild] Wrote {summary['written']} chunks into the lexical index "
        f"({summary['recovered']} read back by query, {summary['already_present']} "
        f"already present, {summary['skipped']} skipped) in {summary['seconds']}s."
    )
    if summary["unrecoverable"]:
        print(
            f"[Rebuild] {len(summary['unrecoverable'])} IDs could not be read by fetch or "
            "by query, so they are absent from the keyword index (likely image chunks "
            "that duplicate a sibling's vector):"
        )
        for vector_id in summary["unrecoverable"][:10]:
            print(f"[Rebuild]   {vector_id[:100]}")

    print(f"[Rebuild] {summary['index']}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the lexical index from Pinecone.")
    parser.add_argument("--limit", type=int, default=None, help="only the first N vectors")
    parser.add_argument("--reset", action="store_true", help="delete existing rows first")
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    parser.add_argument(
        "--no-recover",
        action="store_true",
        help="skip the query fallback for vector IDs fetch cannot read (faster, partial)",
    )
    parser.add_argument(
        "--rewrite-all",
        action="store_true",
        help="re-read and rewrite every chunk, not just the ones missing from the index",
    )
    args = parser.parse_args()

    if not lexical_index.LEXICAL_ENABLED:
        print("[Rebuild] HYBRID_SEARCH_ENABLED is false, so the lexical index is unused.")
        return 0

    summary = rebuild(
        limit=args.limit,
        reset=args.reset,
        dry_run=args.dry_run,
        recover_unfetchable=not args.no_recover,
        rewrite_all=args.rewrite_all,
    )
    return 0 if summary["written"] or summary["already_present"] else 1


if __name__ == "__main__":
    sys.exit(main())
