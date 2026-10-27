"""
Tests for cross-mailbox content deduplication.

These run without Redis: the fingerprinter is pure, and the ledger state machine is
exercised through a small in-memory stand-in plus an explicit "Redis is down" path,
because failing open on an unreachable Redis is a correctness requirement.
"""

import pytest

from services import content_dedup, dedup
from services.content_dedup import (
    ATTACHMENT,
    ATTACHMENT_TEXT,
    BODY,
    STATUS_INDEXED,
    attachment_fingerprint,
    body_fingerprint,
    normalize_body,
)


class FakeRedis:
    """Just enough Redis for the ledger: SET NX, GET, DEL, sets and a pipeline."""

    def __init__(self):
        self.values: dict[str, str] = {}
        self.sets: dict[str, set] = {}
        self.lists: dict[str, list] = {}

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

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)
        return 1

    def sismember(self, key, member):
        return member in self.sets.get(key, set())

    def scard(self, key):
        return len(self.sets.get(key, set()))

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, client):
        self.client = client
        self.queued = []

    def rpush(self, key, value):
        self.queued.append(("rpush", key, value))

    def ltrim(self, key, start, end):
        self.queued.append(("ltrim", key, start, end))

    def sadd(self, key, member):
        self.queued.append(("sadd", key, member))

    def execute(self):
        results = []
        for op in self.queued:
            if op[0] == "rpush":
                self.client.lists.setdefault(op[1], []).append(op[2])
                results.append(1)
            elif op[0] == "ltrim":
                kept = self.client.lists.get(op[1], [])
                # Ledger usage is LTRIM key -N -1: keep the newest N entries.
                if op[3] == -1 and op[2] < 0:
                    kept = kept[op[2] :]
                else:
                    kept = kept[op[2] : (op[3] + 1) or None]
                self.client.lists[op[1]] = kept
                results.append(True)
            elif op[0] == "sadd":
                self.client.sadd(op[1], op[2])
                results.append(1)
        self.queued = []
        return results


@pytest.fixture
def fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(content_dedup, "_client", client)
    monkeypatch.setattr(content_dedup, "_redis_offline", False)
    return client


@pytest.fixture
def redis_offline(monkeypatch):
    monkeypatch.setattr(content_dedup, "_client", None)
    monkeypatch.setattr(content_dedup, "_redis_offline", True)


NOTICE = (
    "The mess bill for August 2025 is attached. Students must clear dues before "
    "5th September 2025. Grade: A. Contact the warden for clarifications."
)


def test_same_broadcast_fingerprints_identically_across_mailboxes():
    """Each recipient's copy differs only in cosmetics: greeting, tracking link,
    quoted history and signature."""
    mailbox_a = (
        "Dear Aman,\n\n"
        f"{NOTICE}\n\n"
        "View online: https://iitj.ac.in/notice?recipient=aman&token=abc123\n"
        "-- \nAman Sharma, B22CS003\n"
    )
    mailbox_b = (
        "Dear Priya,\n\n"
        "THE MESS BILL FOR AUGUST 2025 IS ATTACHED.   Students must clear dues\n"
        "before 5th September 2025.  Grade: A. Contact the warden for clarifications.\n\n"
        "https://iitj.ac.in/notice?recipient=priya&token=xyz789\n"
        "--\nPriya Nair\n"
    )
    # Same notice, forwarded later by a third recipient with the original quoted.
    mailbox_c = (
        "Dear Rahul,\n\n"
        f"{NOTICE}\n\n"
        "On Mon, 1 Sep 2025 at 10:04, warden@iitj.ac.in wrote:\n"
        "> The mess bill for August 2025 is attached.\n"
    )

    fingerprints = {body_fingerprint(text) for text in (mailbox_a, mailbox_b, mailbox_c)}

    assert len(fingerprints) == 1, "the same broadcast must collapse to one fingerprint"
    assert normalize_body(mailbox_a) != ""
    assert "http" not in normalize_body(mailbox_a)


def test_different_notices_do_not_collide():
    other = NOTICE.replace("5th September 2025", "12th December 2025").replace(
        "August 2025", "November 2025"
    )
    assert body_fingerprint(NOTICE) != body_fingerprint(other)


def test_fingerprint_must_not_truncate_at_a_plain_from_line():
    """A 'From:' line inside a body is not a quoted-history marker; cutting there
    could merge two unrelated mails into one fingerprint."""
    first = "From: dean@iitj.ac.in\n" + ("Notice A " * 40)
    second = "From: dean@iitj.ac.in\n" + ("Notice B " * 40)
    assert body_fingerprint(first) != body_fingerprint(second)


def test_attachment_fingerprint_uses_bytes_not_filename():
    bytes_a = b"%PDF-1.4 same circular"
    assert attachment_fingerprint(bytes_a) == attachment_fingerprint(bytes_a)
    assert attachment_fingerprint(bytes_a) != attachment_fingerprint(b"%PDF-1.4 revised circular")


def test_claim_is_first_wins_and_duplicates_see_the_prior_record(fake_redis):
    is_new, payload = content_dedup.claim(
        ATTACHMENT, "hash-1", mailbox="a@iitj.ac.in", message_id="m1", filename="bill.pdf"
    )
    assert is_new and payload["status"] == "pending"

    is_new_again, prior = content_dedup.claim(
        ATTACHMENT, "hash-1", mailbox="b@iitj.ac.in", message_id="m2", filename="bill.pdf"
    )
    assert not is_new_again, "the second mailbox must not re-embed the same bytes"
    assert prior["first_mailbox"] == "a@iitj.ac.in"

    content_dedup.mark_indexed(ATTACHMENT, "hash-1", doc_id="m1:bill.pdf")
    record = content_dedup.get_record(ATTACHMENT, "hash-1")
    assert record["status"] == STATUS_INDEXED
    assert record["doc_id"] == "m1:bill.pdf"

    origins = content_dedup.get_origins(ATTACHMENT, "hash-1")
    assert [origin["mailbox"] for origin in origins] == ["a@iitj.ac.in", "b@iitj.ac.in"]


def test_attachment_text_gate_catches_republished_files(fake_redis):
    """Different bytes, identical text: the second copy must not be embedded."""
    assert content_dedup.claim(ATTACHMENT_TEXT, body_fingerprint(NOTICE), message_id="m1")[0]
    is_new, _ = content_dedup.claim(ATTACHMENT_TEXT, body_fingerprint(NOTICE), message_id="m2")
    assert not is_new


def test_stale_pending_claim_is_reclaimed(fake_redis):
    content_dedup.claim(BODY, "hash-2", mailbox="a@iitj.ac.in", message_id="m1")

    record = content_dedup.get_record(BODY, "hash-2")
    record["first_seen"] = 0  # an ingest attempt that never completed
    fake_redis.values[content_dedup._record_key(BODY, "hash-2")] = content_dedup.json.dumps(record)

    is_new, payload = content_dedup.claim(BODY, "hash-2", mailbox="b@iitj.ac.in", message_id="m2")
    assert is_new, "content must not be stuck forever behind a claim that never finished"
    assert payload["taken_over_from"] == 0


def test_release_lets_a_later_mailbox_retry(fake_redis):
    content_dedup.claim(BODY, "hash-3", mailbox="a@iitj.ac.in", message_id="m1")
    content_dedup.release(BODY, "hash-3")
    is_new, _ = content_dedup.claim(BODY, "hash-3", mailbox="b@iitj.ac.in", message_id="m2")
    assert is_new


def test_ledger_fails_open_when_redis_is_unreachable(redis_offline):
    is_new, prior = content_dedup.claim(BODY, "hash-4", mailbox="a@iitj.ac.in", message_id="m1")
    assert is_new is True and prior is None, "ingestion must proceed without dedup"
    assert content_dedup.get_record(BODY, "hash-4") is None
    assert content_dedup.get_origins(BODY, "hash-4") == []

    # None of these may raise when the ledger is unavailable.
    content_dedup.mark_indexed(BODY, "hash-4", doc_id="m1")
    content_dedup.release(BODY, "hash-4")
    content_dedup.record_origin(BODY, "hash-4", "a@iitj.ac.in", "m1")


def test_message_id_dedup_uses_redis_when_available(fake_redis, monkeypatch, tmp_path):
    # Never point the JSON fallback at the real store: these tests must not touch it.
    monkeypatch.setattr(dedup, "STORE_PATH", str(tmp_path / "processed_message_ids.json"))
    monkeypatch.setattr(dedup, "get_redis", lambda: fake_redis)
    # Pre-seed so the legacy JSON file is not migrated during the test.
    fake_redis.sadd(dedup.REDIS_KEY, "already-there")

    assert dedup.is_already_processed("already-there")
    assert not dedup.is_already_processed("brand-new")

    dedup.mark_processed("brand-new")
    assert dedup.is_already_processed("brand-new")
    assert dedup.store_size() == 2

    dedup.clear_dedup_store()
    assert not dedup.is_already_processed("brand-new")


def test_message_id_dedup_falls_back_to_the_json_store(monkeypatch, tmp_path):
    store = tmp_path / "processed_message_ids.json"
    monkeypatch.setattr(dedup, "get_redis", lambda: None)
    monkeypatch.setattr(dedup, "STORE_PATH", str(store))

    assert not dedup.is_already_processed("m1")
    dedup.mark_processed("m1")
    assert dedup.is_already_processed("m1")
    assert store.exists()
