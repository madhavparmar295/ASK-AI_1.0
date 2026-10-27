"""
Tests for the retention half of the plan: usage tracking on retrieval, the
year-old email purge, the guards that make deletion safe, and the multi-mailbox
helpers.

Everything here runs without Pinecone, PostgreSQL or Gmail; the index and the
ledger are replaced with recording fakes.
"""

import json
import time

import pytest

from jobs import retention_tasks, watch_tasks
from services import content_dedup, usage

CUTOFF = time.time() - 365 * 86400
OLD = CUTOFF - 86400  # older than the cutoff
NEW = CUTOFF + 86400  # newer than the cutoff


class FakeRedis:
    """In-memory stand-in for the parts of Redis this feature uses."""

    def __init__(self):
        self.values = {}
        self.sets = {}
        self.lists = {}
        self.zsets = {}

    def set(self, key, value, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)
        self.sets.pop(key, None)
        self.lists.pop(key, None)

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)
        return 1

    def sismember(self, key, member):
        return member in self.sets.get(key, set())

    def scard(self, key):
        return len(self.sets.get(key, set()))

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)

    def zrangebyscore(self, key, minimum, maximum):
        scores = self.zsets.get(key, {})
        if maximum == "+inf":
            maximum = float("inf")
        return [member for member, score in scores.items() if minimum <= score <= maximum]

    def zcard(self, key):
        return len(self.zsets.get(key, {}))

    def zrem(self, key, *members):
        scores = self.zsets.get(key, {})
        removed = 0
        for member in members:
            if scores.pop(member, None) is not None:
                removed += 1
        return removed

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    def pipeline(self):
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, client):
        self.client = client
        self.queued = []

    def rpush(self, key, value):
        self.queued.append(("rpush", key, value))

    def ltrim(self, key, start, end):
        self.queued.append(("ltrim", key, start, end))

    def execute(self):
        for op in self.queued:
            if op[0] == "rpush":
                self.client.lists.setdefault(op[1], []).append(op[2])
            else:
                items = self.client.lists.get(op[1], [])
                self.client.lists[op[1]] = items[op[2] :] if op[3] == -1 else items
        self.queued = []
        return []


@pytest.fixture
def fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(content_dedup, "_client", client)
    monkeypatch.setattr(content_dedup, "_redis_offline", False)
    return client


def vector(vector_id, source_type, doc_id, last_used=None, ingested_at=None):
    metadata = {"source_type": source_type, "doc_id": doc_id}
    if last_used is not None:
        metadata["last_used"] = last_used
    if ingested_at is not None:
        metadata["ingested_at"] = ingested_at
    return {"id": vector_id, "metadata": metadata}


# --------------------------------------------------------------------------- #
# Usage tracking
# --------------------------------------------------------------------------- #


def test_record_usage_writes_both_stores(fake_redis, monkeypatch):
    touched = {}
    monkeypatch.setattr(usage, "touch_documents", lambda ids, when=None: touched.update({"ids": ids, "when": when}) or len(ids))

    recorded = usage.record_usage(["doc-a", "doc-b", "doc-a"])

    assert recorded == 2, "duplicate doc_ids are collapsed"
    assert touched["ids"] == ["doc-a", "doc-b"]
    assert fake_redis.zrangebyscore(usage.USAGE_KEY, CUTOFF, "+inf") == ["doc-a", "doc-b"]


def test_record_usage_survives_a_failing_metadata_write(fake_redis, monkeypatch):
    def explode(ids, when=None):
        raise RuntimeError("pinecone unavailable")

    monkeypatch.setattr(usage, "touch_documents", explode)

    assert usage.record_usage(["doc-a"]) == 1, "Redis still records usage"
    assert usage.recently_used_doc_ids(CUTOFF) == {"doc-a"}


def test_record_usage_survives_a_missing_ledger(monkeypatch):
    monkeypatch.setattr(content_dedup, "_client", None)
    monkeypatch.setattr(content_dedup, "_redis_offline", True)

    touched = {}
    monkeypatch.setattr(usage, "touch_documents", lambda ids, when=None: touched.update({"ids": ids}) or len(ids))

    assert usage.record_usage(["doc-a"]) == 0, "no Redis, but the call must not raise"
    assert touched["ids"] == ["doc-a"], "Pinecone metadata is still stamped"


def test_missing_usage_data_is_an_error_not_an_empty_set(monkeypatch):
    """An empty set would mean 'nothing was used recently' and delete live content."""
    monkeypatch.setattr(content_dedup, "_client", None)
    monkeypatch.setattr(content_dedup, "_redis_offline", True)

    with pytest.raises(RuntimeError):
        usage.recently_used_doc_ids(CUTOFF)


# --------------------------------------------------------------------------- #
# Retention selection rules
# --------------------------------------------------------------------------- #


def test_old_email_chunks_are_selected_and_other_sources_never_are():
    vectors = [
        vector("mail-1", "email", "doc-mail", last_used=OLD),
        vector("att-1", "email_attachment", "doc-att", last_used=OLD),
        vector("upload-1", "document_upload", "doc-upload", last_used=OLD),
        vector("web-1", "website_pdf", "doc-web", last_used=OLD),
        vector("mail-2", "email", "doc-fresh", last_used=NEW),
    ]

    selection = retention_tasks.select_deletions(vectors, CUTOFF, recently_used=set())

    assert selection["ids"] == ["mail-1", "att-1"]
    assert selection["doc_ids"] == ["doc-mail", "doc-att"]


def test_recently_used_documents_are_protected():
    vectors = [
        vector("mail-1", "email", "doc-used", last_used=OLD),
        vector("mail-2", "email", "doc-idle", last_used=OLD),
    ]

    selection = retention_tasks.select_deletions(vectors, CUTOFF, recently_used={"doc-used"})

    assert selection["ids"] == ["mail-2"], "a document used since the cutoff must be kept"


def test_ingested_at_is_used_when_a_chunk_was_never_retrieved():
    vectors = [
        vector("mail-old", "email", "doc-old", ingested_at=OLD),
        vector("mail-new", "email", "doc-new", ingested_at=NEW),
    ]

    selection = retention_tasks.select_deletions(vectors, CUTOFF, recently_used=set())

    assert selection["ids"] == ["mail-old"]


def test_chunks_without_any_timestamp_are_kept_unless_opted_in():
    vectors = [vector("mail-unknown", "email", "doc-unknown")]

    kept = retention_tasks.select_deletions(vectors, CUTOFF, recently_used=set())
    assert kept["ids"] == []
    assert kept["kept_unstamped"] == ["mail-unknown"]

    opted_in = retention_tasks.select_deletions(
        vectors, CUTOFF, recently_used=set(), include_unstamped=True
    )
    assert opted_in["ids"] == ["mail-unknown"]


def test_unparseable_timestamps_are_kept():
    selection = retention_tasks.select_deletions(
        [vector("mail-broken", "email", "doc-broken", last_used="not-a-timestamp")],
        CUTOFF,
        recently_used=set(),
    )
    assert selection["ids"] == []
    assert selection["kept_unstamped"] == ["mail-broken"]


# --------------------------------------------------------------------------- #
# Retention run: guards and reporting
# --------------------------------------------------------------------------- #


@pytest.fixture
def retention_env(monkeypatch):
    """One stale-query wave holding two deletable chunks plus two protected ones."""
    stale_page = ["mail-1", "mail-2", "keep-1", "upload-1"]
    monkeypatch.setattr(
        retention_tasks,
        "query_ids_by_filter",
        lambda filter_dict, limit=1000: list(stale_page),
    )
    monkeypatch.setattr(
        retention_tasks,
        "fetch_vectors",
        lambda ids: [
            vector("mail-1", "email", "doc-1", last_used=OLD),
            vector("mail-2", "email", "doc-2", last_used=OLD),
            vector("keep-1", "email", "doc-3", last_used=NEW),
            vector("upload-1", "document_upload", "doc-4", last_used=OLD),
        ],
    )
    # 2 candidates out of a 100-vector index (2%), under the default 10% guard.
    monkeypatch.setattr(retention_tasks, "index_size", lambda: 100)
    monkeypatch.setattr(usage, "recently_used_doc_ids", lambda since: set())

    deleted = {}
    monkeypatch.setattr(
        retention_tasks, "delete_vectors", lambda ids, batch_size=500: deleted.update({"ids": ids}) or len(ids)
    )
    forgotten = {}
    monkeypatch.setattr(
        usage, "forget_usage", lambda ids: forgotten.update({"ids": ids}) or len(ids)
    )
    return {"deleted": deleted, "forgotten": forgotten, "stale_page": stale_page}


def test_dry_run_deletes_nothing(retention_env):
    report = retention_tasks.run_retention(dry_run=True)

    assert report["status"] == "dry_run"
    assert report["candidates"] == 2
    assert retention_env["deleted"] == {}


def test_apply_deletes_and_clears_usage(retention_env):
    report = retention_tasks.run_retention(dry_run=False)

    assert report["status"] == "deleted"
    assert report["deleted_vectors"] == 2
    assert retention_env["deleted"]["ids"] == ["mail-1", "mail-2"]
    assert retention_env["forgotten"]["ids"] == ["doc-1", "doc-2"]


def test_large_candidate_set_aborts_unless_forced(retention_env, monkeypatch):
    # 2 candidates out of 100 vectors is 2%, above a 1% guard.
    monkeypatch.setattr(retention_tasks, "MAX_DELETE_FRACTION", 0.01)

    aborted = retention_tasks.run_retention(dry_run=False)
    assert aborted["status"] == "aborted"
    assert retention_env["deleted"] == {}, "the guard must stop deletion"

    forced = retention_tasks.run_retention(dry_run=False, force=True)
    assert forced["status"] == "deleted"


def test_run_aborts_when_usage_data_is_unavailable(retention_env, monkeypatch):
    def unavailable(since):
        raise RuntimeError("redis down")

    monkeypatch.setattr(usage, "recently_used_doc_ids", unavailable)

    report = retention_tasks.run_retention(dry_run=False)

    assert report["status"] == "aborted"
    assert retention_env["deleted"] == {}, "never delete without usage data"


def test_nothing_to_delete_is_reported_cleanly(retention_env, monkeypatch):
    monkeypatch.setattr(
        retention_tasks,
        "fetch_vectors",
        lambda ids: [vector("keep-1", "email", "doc-3", last_used=NEW)],
    )

    report = retention_tasks.run_retention(dry_run=False)

    assert report["status"] == "nothing_to_delete"
    assert retention_env["deleted"] == {}


def test_apply_works_through_more_candidates_than_one_query_returns(retention_env, monkeypatch):
    """A full result page cannot be paged past without deleting it first, so the
    apply path works through candidates in waves."""
    monkeypatch.setattr(retention_tasks, "QUERY_LIMIT", 1)
    pending = ["mail-1", "mail-2"]

    # Mirrors Pinecone: the stale filter keeps returning the same matches until
    # they are deleted, and the unstamped query is separate.
    monkeypatch.setattr(
        retention_tasks,
        "query_ids_by_filter",
        lambda filter_dict, limit=1000: list(pending) if "$lt" in str(filter_dict) else [],
    )
    monkeypatch.setattr(
        retention_tasks,
        "fetch_vectors",
        lambda ids: [
            {
                "id": vector_id,
                "metadata": {"source_type": "email", "doc_id": vector_id, "last_used": OLD},
            }
            for vector_id in ids
        ],
    )

    def delete_now(ids, batch_size=500):
        for vector_id in ids:
            pending.remove(vector_id)
        retention_env["deleted"].setdefault("ids", []).extend(ids)
        return len(ids)

    monkeypatch.setattr(retention_tasks, "delete_vectors", delete_now)

    report = retention_tasks.run_retention(dry_run=False, force=True)

    assert report["candidates"] == 2
    assert report["deleted_vectors"] == 2
    assert retention_env["deleted"]["ids"] == ["mail-1", "mail-2"]


def test_dry_run_flags_when_more_candidates_may_exist(retention_env, monkeypatch):
    monkeypatch.setattr(retention_tasks, "QUERY_LIMIT", 2)  # matches the full page
    monkeypatch.setattr(
        retention_tasks,
        "fetch_vectors",
        lambda ids: [
            vector("mail-1", "email", "doc-1", last_used=OLD),
            vector("mail-2", "email", "doc-2", last_used=OLD),
        ],
    )

    report = retention_tasks.run_retention(dry_run=True)

    assert report["status"] == "dry_run"
    assert report["page_limit_reached"] is True
    assert retention_env["deleted"] == {}


def test_scheduled_task_is_inert_until_armed(monkeypatch):
    monkeypatch.setattr(retention_tasks, "RETENTION_ENABLED", False)

    result = retention_tasks.purge_unused_email_chunks_task()

    assert result["status"] == "disabled"


# --------------------------------------------------------------------------- #
# Email path has no PostgreSQL dependency
# --------------------------------------------------------------------------- #


def test_email_ingestion_writes_only_to_pinecone(monkeypatch):
    from jobs import email_tasks
    from services import ingest

    def no_postgres(*args, **kwargs):
        raise AssertionError("the email path must not touch PostgreSQL")

    monkeypatch.setattr(ingest, "upsert_document", no_postgres)
    monkeypatch.setattr(ingest, "embed_document", no_postgres)
    monkeypatch.setattr(ingest, "mark_pinecone_indexed", no_postgres)

    upserted = {}
    monkeypatch.setattr(
        ingest,
        "embed_chunks",
        lambda texts: [[0.0] * 1024 for _ in texts],
    )
    monkeypatch.setattr(
        ingest, "upsert_chunks", lambda chunks, embeddings: upserted.update({"chunks": chunks})
    )

    monkeypatch.setattr(
        email_tasks,
        "extract_from_email",
        lambda message, gmail=None: [
            {
                "text": "Mess bill for August 2025.",
                "doc_id": "19db6b951e5d9cef",
                "source": "body",
                "filename": "body",
                "source_type": "email",
                "access_level": "public",
                "sender": "warden@iitj.ac.in",
                "subject": "Mess Bill",
                "date": "Mon, 1 Sep 2025",
                "_content_fingerprints": [("body", "hash-1")],
            }
        ],
    )

    marked = {}
    monkeypatch.setattr(
        email_tasks, "mark_indexed", lambda kind, fingerprint, doc_id: marked.update({"doc_id": doc_id})
    )
    monkeypatch.setattr(email_tasks, "release", lambda kind, fingerprint: marked.update({"released": True}))

    email_tasks._index_email({"id": "19db6b951e5d9cef"})

    assert upserted["chunks"], "chunks reached Pinecone"
    assert marked["doc_id"] == "19db6b951e5d9cef", "the fingerprint is marked indexed"
    assert "released" not in marked


# --------------------------------------------------------------------------- #
# Multi-mailbox helpers
# --------------------------------------------------------------------------- #


def test_configured_accounts_parses_and_dedupes(monkeypatch):
    from services import gmail_auth

    monkeypatch.setenv("GMAIL_ACCOUNT_IDS", " a@iitj.ac.in ,b@iitj.ac.in, a@iitj.ac.in ,")
    assert gmail_auth.configured_accounts() == ["a@iitj.ac.in", "b@iitj.ac.in"]


def test_configured_accounts_falls_back_to_stored_tokens(monkeypatch, tmp_path):
    from services import gmail_auth

    monkeypatch.delenv("GMAIL_ACCOUNT_IDS", raising=False)
    (tmp_path / "one@iitj.ac.in.json").write_text("{}", encoding="utf-8")
    (tmp_path / "two@iitj.ac.in.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gmail_auth, "TOKEN_STORE_PATH", str(tmp_path / "{user_id}.json"))

    assert gmail_auth.configured_accounts() == ["one@iitj.ac.in", "two@iitj.ac.in"]


def test_watch_renewal_isolates_failures(monkeypatch):
    monkeypatch.setattr(
        watch_tasks, "configured_accounts", lambda: ["a@iitj.ac.in", "b@iitj.ac.in", "c@iitj.ac.in"]
    )

    def register(account):
        if account == "b@iitj.ac.in":
            raise RuntimeError("token revoked")
        return {"history_id": "12345"}

    monkeypatch.setattr(watch_tasks, "register_watch", register)

    result = watch_tasks.renew_all_watches()

    assert result["accounts"] == 3
    assert result["renewed"] == 2, "one broken mailbox must not stop the others"
    assert result["results"]["b@iitj.ac.in"].startswith("error")
    assert json.dumps(result)  # report is serialisable for the task result backend
