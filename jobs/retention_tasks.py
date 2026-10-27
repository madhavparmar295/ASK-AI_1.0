"""
Retention: delete email chunks that have not been used for a year.

Only email content is eligible. Manual uploads (``document_upload``) and website
PDFs (``website_pdf`` / ``website``) are never deleted, whatever their age.

Deleting is driven by metadata the pipeline already maintains:

    source_type   which family the chunk belongs to
    last_used     epoch seconds, stamped on every retrieval
    ingested_at   epoch seconds, stamped when the chunk was indexed

A document is deleted only when it looks abandoned in *both* places: Pinecone
metadata says it was last used before the cutoff, and Redis has no newer usage
timestamp for it. Retrieval writes both, and the Redis copy is what protects a
document whose metadata stamp failed.

Finding candidates uses a metadata filter rather than walking the index, so the
job costs one query per batch of stale chunks instead of one request per 100
vectors in the whole corpus.

Safety rails, because deletion is irreversible:

    * dry run by default, and the scheduled run does nothing at all until
      RETENTION_ENABLED is true
    * aborts when Redis is unavailable instead of guessing what is unused
    * aborts when the candidate set exceeds RETENTION_MAX_FRACTION of the index,
      unless explicitly forced
    * chunks with no usage information are only deleted when ``include_unstamped``
      is requested, so a first run cannot wipe the pre-existing corpus

Run manually:

    python -m jobs.retention_tasks                     # dry run report
    python -m jobs.retention_tasks --apply             # delete
    python -m jobs.retention_tasks --days 730 --apply  # different age
"""

import argparse
import os
import time

from jobs.celery_app import celery_app
from services import usage
from services.vectorstore import delete_vectors, fetch_vectors, index_size, query_ids_by_filter

# Chunk families retention is allowed to touch.
EMAIL_SOURCE_TYPES = ("email", "email_attachment")

RETENTION_ENABLED = os.getenv("RETENTION_ENABLED", "false").lower() in ("1", "true", "yes")
RETENTION_DRY_RUN = os.getenv("RETENTION_DRY_RUN", "true").lower() not in ("0", "false", "no")
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "365"))
MAX_DELETE_FRACTION = float(os.getenv("RETENTION_MAX_FRACTION", "0.1"))

# How many candidates one filtered query returns. Deletion happens in waves of
# this size, so the apply path can work through more matches than a single query
# can return.
QUERY_LIMIT = int(os.getenv("RETENTION_QUERY_LIMIT", "10000"))


def stale_email_filter(cutoff: float) -> dict:
    """Email chunks whose last use is older than the cutoff."""
    return {
        "$and": [
            {"source_type": {"$in": list(EMAIL_SOURCE_TYPES)}},
            {"last_used": {"$lt": cutoff}},
        ]
    }


def unstamped_email_filter() -> dict:
    """Email chunks that have never been stamped with a use timestamp."""
    return {
        "$and": [
            {"source_type": {"$in": list(EMAIL_SOURCE_TYPES)}},
            {"last_used": {"$exists": False}},
        ]
    }


def select_deletions(
    vectors: list[dict],
    cutoff: float,
    recently_used: set[str],
    include_unstamped: bool = False,
) -> dict:
    """
    Decide which vectors in this batch may be deleted.

    Pure function: every input is plain data, so the selection rules are testable
    without touching Pinecone. Returns::

        {"ids": [...], "doc_ids": [...], "kept_unstamped": [...]}
    """
    ids: list[str] = []
    doc_ids: list[str] = []
    kept_unstamped: list[str] = []

    for vector in vectors:
        metadata = vector.get("metadata") or {}

        if metadata.get("source_type") not in EMAIL_SOURCE_TYPES:
            continue  # uploads and website PDFs are never deleted

        doc_id = str(metadata.get("doc_id") or "")
        if doc_id and doc_id in recently_used:
            continue  # used recently according to Redis

        stamped = metadata.get("last_used")
        if stamped is None:
            stamped = metadata.get("ingested_at")

        if stamped is None:
            # No evidence either way: keep it unless the caller explicitly opts in.
            if include_unstamped:
                ids.append(vector["id"])
                doc_ids.append(doc_id)
            else:
                kept_unstamped.append(vector["id"])
            continue

        try:
            is_old = float(stamped) < cutoff
        except (TypeError, ValueError):
            kept_unstamped.append(vector["id"])
            continue

        if is_old:
            ids.append(vector["id"])
            doc_ids.append(doc_id)

    return {"ids": ids, "doc_ids": doc_ids, "kept_unstamped": kept_unstamped}


def count_unstamped_email_chunks() -> tuple[int, bool]:
    """
    How many email chunks have no usage information at all.

    Returns (count, capped). A single query returns at most QUERY_LIMIT matches, so
    a count that hits that limit is a lower bound rather than the real total.
    """
    found = query_ids_by_filter(unstamped_email_filter(), limit=QUERY_LIMIT)
    return len(found), len(found) >= QUERY_LIMIT


def run_retention(
    dry_run: bool | None = None,
    older_than_days: int | None = None,
    include_unstamped: bool = False,
    force: bool = False,
) -> dict:
    """Plan and, unless dry running, perform the purge. Returns a report dict."""
    dry_run = RETENTION_DRY_RUN if dry_run is None else dry_run
    days = RETENTION_DAYS if older_than_days is None else older_than_days
    cutoff = time.time() - days * 86400

    report: dict = {
        "status": "planned",
        "dry_run": dry_run,
        "older_than_days": days,
        "cutoff": cutoff,
    }

    # Without usage data we cannot tell used from unused, so refuse to delete.
    try:
        recently_used = usage.recently_used_doc_ids(cutoff)
    except Exception as exc:
        report.update({"status": "aborted", "reason": f"usage data unavailable: {exc}"})
        print(f"[Retention] Aborted: {exc}")
        return report

    total_vectors = index_size() or 1
    unstamped, unstamped_capped = count_unstamped_email_chunks()

    filters = [stale_email_filter(cutoff)]
    if include_unstamped:
        filters.append(unstamped_email_filter())

    candidates = 0
    deleted = 0
    page_limit_reached = False

    for filter_dict in filters:
        seen: set[str] = set()

        while True:
            found = query_ids_by_filter(filter_dict, limit=QUERY_LIMIT)
            page = [vector_id for vector_id in found if vector_id not in seen]
            seen.update(page)
            complete_page = len(found) < QUERY_LIMIT

            if not page:
                break

            selection = select_deletions(
                fetch_vectors(page), cutoff, recently_used, include_unstamped=include_unstamped
            )
            candidates += len(selection["ids"])

            fraction = candidates / total_vectors
            if fraction > MAX_DELETE_FRACTION and not force:
                report.update(
                    {
                        "status": "aborted",
                        "candidates": candidates,
                        "candidate_fraction": round(fraction, 4),
                        "reason": (
                            f"candidates are {fraction:.2%} of the index, above the "
                            f"{MAX_DELETE_FRACTION:.0%} guard; re-run with force to override"
                        ),
                    }
                )
                print(f"[Retention] Aborted: {report['reason']}")
                return report

            if not dry_run and selection["ids"]:
                # Deleting this wave is also what exposes the next one to the query.
                deleted += delete_vectors(selection["ids"])
                usage.forget_usage(selection["doc_ids"])

            if complete_page:
                break  # the filter had nothing more to give

            if dry_run or not selection["ids"]:
                # Without deleting we cannot page past a full result set, and a page
                # with nothing deletable would repeat forever.
                page_limit_reached = True
                break

    fraction = candidates / total_vectors
    report.update(
        {
            "index_vectors": total_vectors,
            "recently_used_documents": len(recently_used),
            "candidates": candidates,
            "candidate_fraction": round(fraction, 4),
            "kept_without_usage_data": unstamped,
            "kept_without_usage_data_capped": unstamped_capped,
            "page_limit_reached": page_limit_reached,
            "deleted_vectors": deleted,
        }
    )

    unstamped_display = f"{'>=' if unstamped_capped else ''}{unstamped}"
    print(
        f"[Retention] Index {total_vectors} vectors | candidates: {candidates} "
        f"({fraction:.2%}) | email chunks with no usage data (kept): {unstamped_display}"
    )

    if candidates == 0:
        report["status"] = "nothing_to_delete"
        return report

    if dry_run:
        report["status"] = "dry_run"
        if page_limit_reached:
            print(
                "[Retention] Dry run: nothing deleted. More candidates may exist than "
                f"one query returns ({QUERY_LIMIT}); run with --apply to work through them."
            )
        else:
            print(f"[Retention] Dry run: nothing deleted. Would delete {candidates} chunks.")
        return report

    report["status"] = "deleted"
    print(f"[Retention] Deleted {deleted} email chunks.")
    return report


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def purge_unused_email_chunks_task(self, dry_run: bool | None = None, force: bool = False):
    """Scheduled entry point. Does nothing until RETENTION_ENABLED is true."""
    if not RETENTION_ENABLED:
        message = (
            "Retention is disabled (set RETENTION_ENABLED=true to arm it and "
            "RETENTION_DRY_RUN=false to actually delete)."
        )
        print(f"[Retention] {message}")
        return {"status": "disabled", "message": message}

    try:
        return run_retention(dry_run=dry_run, force=force)
    except Exception as exc:
        print(f"[Retention] Run failed: {exc}")
        raise self.retry(exc=exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete email chunks that are no longer used.")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default: dry run)")
    parser.add_argument("--days", type=int, default=None, help="Age in days (default 365)")
    parser.add_argument(
        "--include-unstamped",
        action="store_true",
        help="Also delete email chunks with no usage or ingestion timestamp",
    )
    parser.add_argument("--force", action="store_true", help="Ignore the max-delete-fraction guard")
    args = parser.parse_args()

    report = run_retention(
        dry_run=not args.apply,
        older_than_days=args.days,
        include_unstamped=args.include_unstamped,
        force=args.force,
    )
    print(f"[Retention] Report: {report}")


if __name__ == "__main__":
    main()
