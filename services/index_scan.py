"""
Walk every vector in the Pinecone index.

The index is the only complete record of what is searchable: documents can be
deleted from Postgres, and a local database is not always available. Reading it
therefore needs the index's own listing API rather than a similarity query - with
the cosine metric a zero-vector query ranks arbitrarily, so it can never be used to
enumerate a collection.

``list_paginated`` walks IDs in a stable order and ``fetch`` returns their metadata,
so this module provides both a full scan and a batched iteration for the rebuild,
audit and load scripts.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

from services.vectorstore import FETCH_ID_LIMIT, fetch_vectors, get_index

_logger = logging.getLogger("askai.scan")

# The listing endpoint rejects a page larger than 100, whatever batch size a caller
# asks for, so it is capped here rather than surfacing a 400 from Pinecone.
MAX_LIST_PAGE = 100
DEFAULT_PAGE_SIZE = MAX_LIST_PAGE

# Fetch passes IDs in the request line and returns nothing at all for an ID containing
# one of these characters - not an error, just an empty result - while list_paginated
# reports the ID and a query by ID finds the vector. In this corpus those are the
# attachment chunks written as ``{doc_id}:{filename}-{chunk}``, whose filenames contain
# spaces and plus signs: roughly one vector in six. Reading them back needs the query
# path instead, which is slower, so it is opt-in.
UNFETCHABLE_ID_CHARS = (" ", "+", "%", "#", "&")

# One query per unreadable vector would take hours for a corpus this size, so the reads
# run in parallel. Eight is enough to saturate the client without tripping the service's
# own request-rate limits.
RECOVERY_WORKERS = int(os.getenv("INDEX_SCAN_RECOVERY_WORKERS", "8"))

_unrecoverable: set[str] = set()


def is_fetchable_id(vector_id: str) -> bool:
    return not any(char in vector_id for char in UNFETCHABLE_ID_CHARS)


def unrecoverable_ids() -> set[str]:
    """
    IDs that neither fetch nor query-by-ID returned, for reporting.

    A handful of image chunks exist only as an exact duplicate of their sibling, so a
    query by ID answers with the sibling and the row stays missing. Reporting them beats
    silently ending up a few rows short of the vector count.
    """
    return set(_unrecoverable)


def recover_by_id(vector_id: str) -> dict | None:
    """
    Read one vector's metadata by querying it, for an ID fetch cannot carry.

    A query by ID returns the vector itself as its own best match, which is how the
    metadata of an otherwise-unreadable chunk is recovered.
    """
    try:
        response = get_index().query(id=vector_id, top_k=1, include_metadata=True)
    except Exception as exc:
        _logger.warning("could not recover %s: %s", str(vector_id)[:60], exc)
        return None

    for match in getattr(response, "matches", None) or []:
        matched_id = getattr(match, "id", None)
        if matched_id == vector_id:
            return {"id": vector_id, "metadata": getattr(match, "metadata", None) or {}}

    _unrecoverable.add(vector_id)
    return None


def fetch_batch(ids: list[str], recover_unfetchable: bool = False) -> list[dict]:
    """Fetch a batch, optionally recovering the IDs the fetch endpoint cannot return."""
    records = fetch_vectors(ids)
    if not recover_unfetchable:
        return records

    returned = {record["id"] for record in records}
    missing = [
        vector_id
        for vector_id in ids
        if vector_id not in returned and not is_fetchable_id(vector_id)
    ]
    if not missing:
        return records

    with ThreadPoolExecutor(max_workers=max(1, min(RECOVERY_WORKERS, len(missing)))) as pool:
        # ``map`` keeps the batch in ID order, so a rebuilt index is reproducible.
        recovered = list(pool.map(recover_by_id, missing))
    records.extend(record for record in recovered if record)
    return records


def iter_vector_ids(page_size: int = DEFAULT_PAGE_SIZE, limit: int | None = None) -> Iterator[str]:
    """Yield every vector ID in the index, one page at a time."""
    index = get_index()
    page_size = max(1, min(page_size, MAX_LIST_PAGE))
    token = None
    seen = 0

    while True:
        response = index.list_paginated(limit=page_size, pagination_token=token)
        vectors = getattr(response, "vectors", None) or []

        for vector in vectors:
            vector_id = vector.get("id") if isinstance(vector, dict) else getattr(vector, "id", None)
            if not vector_id:
                continue
            yield vector_id
            seen += 1
            if limit and seen >= limit:
                return

        pagination = getattr(response, "pagination", None)
        token = None
        if pagination is not None:
            token = (
                pagination.get("next")
                if isinstance(pagination, dict)
                else getattr(pagination, "next", None)
            )
        if not token:
            return


def iter_records(
    batch_size: int = 100,
    limit: int | None = None,
    ids: list[str] | None = None,
    recover_unfetchable: bool = False,
) -> Iterator[list[dict]]:
    """
    Yield ``[{id, metadata}, ...]`` batches for the whole index (or for ``ids``).

    Fetch carries IDs in the request line, so batches stay within the documented
    limit; ``fetch_vectors`` also splits a batch that overflows.

    With ``recover_unfetchable`` every ID the fetch endpoint refuses is read back
    through a query instead, which costs one query per affected vector and is worth it
    when the result is used to rebuild an index rather than to answer a question.
    """
    size = max(1, min(batch_size, FETCH_ID_LIMIT, MAX_LIST_PAGE))

    if ids is not None:
        for start in range(0, len(ids), size):
            yield fetch_batch(ids[start : start + size], recover_unfetchable)
        return

    batch: list[str] = []
    for vector_id in iter_vector_ids(page_size=size, limit=limit):
        batch.append(vector_id)
        if len(batch) >= size:
            yield fetch_batch(batch, recover_unfetchable)
            batch = []

    if batch:
        yield fetch_batch(batch, recover_unfetchable)


def scan(limit: int | None = None) -> dict:
    """
    Summary of the index: how many vectors, and how many carry metadata at all.

    Cheap enough for a health check; the full metadata read is what the audit script
    does.
    """
    total = 0
    with_metadata = 0
    for batch in iter_records(batch_size=FETCH_ID_LIMIT, limit=limit):
        for record in batch:
            total += 1
            if record.get("metadata"):
                with_metadata += 1

    return {"vectors": total, "with_metadata": with_metadata, "limit": limit}
