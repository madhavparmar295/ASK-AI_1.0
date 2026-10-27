"""
End-to-end check of the ingestion gate: the same broadcast delivered to two
mailboxes must be saved, extracted and embedded exactly once.

The real ``extract_from_email`` pipeline runs here. Only the network/disk edges
(Gmail download, file storage, document parsing, sender allow-list) are replaced,
so the fingerprint and claiming logic under test is the production code path.
"""

import base64

import pytest

from services import content_dedup, email_processing
from services.content_dedup import ATTACHMENT, ATTACHMENT_TEXT, BODY

NOTICE = (
    "The mess bill for August 2025 is attached. Students must clear dues before "
    "5th September 2025. Grade: A. Contact the warden for clarifications."
)
ATTACHMENT_BYTES = b"%PDF-1.4 the same mess bill bytes for every recipient"
EXTRACTED_ATTACHMENT_TEXT = NOTICE + "\nTotal payable: 4200 INR"


class FakeRedis:
    """In-memory stand-in for the ledger Redis client."""

    def __init__(self):
        self.values = {}
        self.lists = {}

    def set(self, key, value, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)
        self.lists.pop(key, None)

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


def _gmail_message(message_id: str, delivered_to: str, body_text: str, with_attachment: bool):
    def encoded(text: str) -> str:
        return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")

    parts = [{"mimeType": "text/plain", "body": {"data": encoded(body_text)}}]
    if with_attachment:
        parts.append(
            {
                "mimeType": "application/pdf",
                "filename": "bill.pdf",
                "headers": [
                    {"name": "Content-Disposition", "value": 'attachment; filename="bill.pdf"'}
                ],
                "body": {"data": base64.urlsafe_b64encode(ATTACHMENT_BYTES).decode("ascii")},
            }
        )

    return {
        "id": message_id,
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "warden@iitj.ac.in"},
                {"name": "Subject", "value": "Mess Bill August 2025"},
                {"name": "Date", "value": "Mon, 1 Sep 2025 10:00:00 +0530"},
                {"name": "Delivered-To", "value": delivered_to},
            ],
            "parts": parts,
        },
    }


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """Wire the pipeline with a fake ledger and a temp storage directory."""
    client = FakeRedis()
    monkeypatch.setattr(content_dedup, "_client", client)
    monkeypatch.setattr(content_dedup, "_redis_offline", False)

    saved = []

    def fake_save(contents: bytes, filename: str) -> str:
        path = tmp_path / f"{len(saved)}_{filename}"
        path.write_bytes(contents)
        saved.append(path)
        return str(path)

    monkeypatch.setattr(email_processing, "save_file", fake_save)
    monkeypatch.setattr(email_processing, "load_document", lambda path: EXTRACTED_ATTACHMENT_TEXT)
    monkeypatch.setattr(email_processing, "attachment_required_ocr", lambda path, ext: False)
    monkeypatch.setattr(email_processing, "get_cached_ocr_result", lambda content_hash: None)
    monkeypatch.setattr(email_processing, "store_ocr_result", lambda content_hash, text: None)
    monkeypatch.setattr(email_processing, "is_allowed_sender", lambda sender: True)
    monkeypatch.setattr(email_processing, "is_already_processed", lambda message_id: False)
    monkeypatch.setattr(email_processing, "mark_processed", lambda message_id: None)

    return {"client": client, "saved": saved}


def _body_of(text: str, recipient: str) -> str:
    return (
        f"Dear {recipient},\n\n"
        f"{text}\n\n"
        f"View online: https://iitj.ac.in/notice?recipient={recipient}&token={recipient}123\n"
        "-- \nOffice of the Warden\n"
    )


def test_second_mailbox_does_not_re_save_or_re_embed(pipeline):
    first = email_processing.extract_from_email(
        _gmail_message("aaaabbbbccccdddd", "aman@iitj.ac.in", _body_of(NOTICE, "Aman"), True)
    )
    assert len(first) == 2, "body + attachment on the first arrival"
    assert len(pipeline["saved"]) == 1, "the attachment is written to disk once"

    second = email_processing.extract_from_email(
        _gmail_message("eeeeffff00001111", "priya@iitj.ac.in", _body_of(NOTICE, "Priya"), True)
    )
    assert second == [], "the same broadcast from another mailbox must not be ingested again"
    assert len(pipeline["saved"]) == 1, "no second copy of the attachment on disk"

    body_hash = content_dedup.body_fingerprint(_body_of(NOTICE, "Aman"))
    attachment_hash = content_dedup.attachment_fingerprint(ATTACHMENT_BYTES)
    assert content_dedup.get_origins(BODY, body_hash)[-1]["mailbox"] == "priya@iitj.ac.in"
    assert content_dedup.get_origins(ATTACHMENT, attachment_hash)[-1]["mailbox"] == "priya@iitj.ac.in"

    # Records carry the fingerprints the caller uses to mark them indexed.
    fingerprints = dict(first[0]["_content_fingerprints"])
    assert fingerprints[BODY] == body_hash
    assert dict(first[1]["_content_fingerprints"])[ATTACHMENT] == attachment_hash
    assert dict(first[1]["_content_fingerprints"])[ATTACHMENT_TEXT]


def test_a_genuinely_new_notice_is_still_ingested(pipeline):
    email_processing.extract_from_email(
        _gmail_message("aaaabbbbccccdddd", "aman@iitj.ac.in", _body_of(NOTICE, "Aman"), True)
    )

    revised = NOTICE.replace("5th September 2025", "20th September 2025")
    records = email_processing.extract_from_email(
        _gmail_message("eeeeffff00001111", "priya@iitj.ac.in", _body_of(revised, "Priya"), False)
    )

    assert len(records) == 1, "a revised deadline is new content, not a duplicate"
    assert records[0]["source"] == "body"


def test_same_pdf_republished_with_different_bytes_is_caught_by_text(pipeline, monkeypatch):
    """Re-saved/renamed copies have new bytes but identical text."""
    email_processing.extract_from_email(
        _gmail_message("aaaabbbbccccdddd", "aman@iitj.ac.in", _body_of(NOTICE, "Aman"), True)
    )

    monkeypatch.setattr(email_processing, "load_document", lambda path: EXTRACTED_ATTACHMENT_TEXT)
    reencoded = bytes(reversed(ATTACHMENT_BYTES))  # different bytes, same extracted text

    def similar_attachment(message_id, delivered_to, body_text):
        message = _gmail_message(message_id, delivered_to, body_text, with_attachment=False)
        message["payload"]["parts"].append(
            {
                "mimeType": "application/pdf",
                "filename": "bill-final.pdf",
                "body": {"data": base64.urlsafe_b64encode(reencoded).decode("ascii")},
            }
        )
        return message

    second = email_processing.extract_from_email(
        similar_attachment("eeeeffff00001111", "priya@iitj.ac.in", _body_of(NOTICE, "Priya"))
    )

    assert second == [], "identical extracted text must not be embedded twice"
    assert len(pipeline["saved"]) == 2, "only the first copy of each byte-stream is stored"


def test_ingestion_still_works_when_the_ledger_is_unreachable(pipeline, monkeypatch):
    monkeypatch.setattr(content_dedup, "_client", None)
    monkeypatch.setattr(content_dedup, "_redis_offline", True)

    for index in range(2):
        records = email_processing.extract_from_email(
            _gmail_message(
                f"aaaabbbbccccdd{index:02d}",
                "aman@iitj.ac.in",
                _body_of(NOTICE, "Aman"),
                True,
            )
        )
        assert len(records) == 2, "without the ledger the pipeline must behave as before"
