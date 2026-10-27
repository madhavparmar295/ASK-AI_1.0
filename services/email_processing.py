"""
Single shared entry point for extracting structured, protected, tagged
content from a raw Gmail message.

Used by both historical backfill and real-time ingestion.

Pipeline per email:

    sender check
    -> dedup check
    -> body + each attachment dispatched to the right extractor
    -> OCR-cache check/write for attachments that actually needed OCR
    -> PII hashing (roll numbers, grades)
    -> access-level classification
    -> return one record per body/attachment
"""

import base64
import os
import tempfile
from html.parser import HTMLParser

from services.attachment_processor import (
    process_attachment,
    attachment_required_ocr,
)
from services.pii import apply_pii_protection
from services.access_control import classify_access_level
from services.ocr_cache import (
    get_cached_ocr_result,
    store_ocr_result,
)
from services.dedup import (
    is_already_processed,
    mark_processed,
)
from services.content_dedup import (
    ATTACHMENT,
    ATTACHMENT_TEXT,
    BODY,
    attachment_fingerprint,
    body_fingerprint,
    claim,
)
from services.storage import save_file
from services.sender_filter import is_allowed_sender


class _HTMLTextExtractor(HTMLParser):
    """Small standard-library HTML -> text converter."""

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self):
        return " ".join(self.parts)


def _extract_headers(message: dict) -> dict:
    headers = message.get("payload", {}).get("headers", [])

    header_map = {
        h.get("name", "").lower(): h.get("value", "")
        for h in headers
        if isinstance(h, dict)
    }

    return {
        "sender": header_map.get("from", ""),
        "subject": header_map.get("subject", "No Subject"),
        "date": header_map.get("date", ""),
        # Which mailbox received this message. Without it a broadcast that reaches
        # many inboxes cannot be traced back to its origins.
        "mailbox": (
            header_map.get("delivered-to")
            or header_map.get("x-original-to")
            or header_map.get("to", "")
        ),
    }


def extract_from_email(
    message: dict,
    gmail=None,
) -> list[dict]:
    """
    Extract structured records from one Gmail message.

    Returns one record per email body/attachment, ready for
    chunking and embedding.
    """

    message_id = message["id"]

    # Second sender-protection layer.
    # email_tasks.py already performs an early metadata check,
    # but extraction must protect itself as well.
    email_meta = _extract_headers(message)

    if not is_allowed_sender(email_meta.get("sender", "")):
        print(
            f"[Sender Filter] Rejected message {message_id}: "
            f"{email_meta.get('sender', '')}"
        )
        return []

    if is_already_processed(message_id):
        return []

    records = []

    body_text = _extract_body(message)

    if body_text.strip():
        # The identical broadcast arrives in every mailbox, so fingerprint the
        # normalized body and embed it only the first time it is seen.
        body_hash = body_fingerprint(body_text)
        body_is_new, body_prior = claim(
            BODY,
            body_hash,
            mailbox=email_meta.get("mailbox", ""),
            message_id=message_id,
        )

        if body_is_new:
            body_record = _build_record(
                body_text,
                source="body",
                doc_id=message_id,
                meta=email_meta,
            )
            body_record["_content_fingerprints"] = [(BODY, body_hash)]
            records.append(body_record)
        else:
            body_prior = body_prior or {}
            print(
                f"[ContentDedup] Body of {message_id} already indexed as doc "
                f"'{body_prior.get('doc_id') or 'unknown'}'; skipping embed."
            )

    for attachment in _get_attachments(
        message,
        gmail=gmail,
    ):
        record = _process_single_attachment(
            attachment,
            message_id,
            meta=email_meta,
        )

        if record is not None:
            records.append(record)

    mark_processed(message_id)

    return records


import re
from datetime import datetime, timezone
from services.storage import is_allowed_file, save_file
from services.document_loader import load_document
from services.rate_limiter import acquire_token


def _safe_b64decode(data: str | bytes) -> bytes:
    """Safely decode base64 / base64url data, adding missing padding."""
    if not data:
        return b""
    if isinstance(data, str):
        data = data.encode("utf-8")
    data = data.replace(b"-", b"+").replace(b"_", b"/")
    pad = b"=" * ((4 - len(data) % 4) % 4)
    try:
        return base64.b64decode(data + pad)
    except Exception as exc:
        print(f"[Attachment] Base64 decode failed: {exc}")
        return b""


def _build_record(
    raw_text: str,
    source: str,
    doc_id: str,
    meta: dict = None,
    filename: str = "",
) -> dict:
    protected_text = apply_pii_protection(raw_text)
    access_level = classify_access_level(protected_text)

    record = {
        "text": protected_text,
        "embed_text": protected_text,
        "source": source,
        "source_type": "email",
        "access_level": access_level,
        "doc_id": doc_id,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "attachment_path": None,
    }

    if meta:
        sender = meta.get("sender", "")
        subject = meta.get("subject", "")
        date = meta.get("date", "")

        header_prefix = (
            f"[Sender: {sender} | "
            f"Subject: {subject} | "
            f"Date: {date}]\n"
        )

        record["text"] = header_prefix + protected_text
        record["embed_text"] = header_prefix + protected_text
        record["sender"] = sender
        record["subject"] = subject
        record["date"] = date
        record["filename"] = filename if filename else source

    return record


def _build_attachment_record(
    extracted_text: str,
    filename: str,
    doc_id: str,
    saved_path: str,
    meta: dict = None,
) -> dict:
    """Build an attachment record formatted exactly like manual uploaded docs."""
    protected_text = apply_pii_protection(extracted_text)
    access_level = classify_access_level(protected_text)

    sender = meta.get("sender", "") if meta else ""
    subject = meta.get("subject", "") if meta else ""
    date = meta.get("date", "") if meta else ""

    header_prefix = (
        f"[Sender: {sender} | "
        f"Subject: {subject} | "
        f"Date: {date}]\n"
        f"[Attachment: {filename}]\n"
    )

    return {
        # text is intentionally empty for postgres content column, like manual uploads
        "text": "",
        # embed_text includes header + extracted text for 384-d HNSW vector embedding
        "embed_text": header_prefix + protected_text,
        "doc_id": doc_id,
        "source": filename,
        "filename": filename,
        "source_type": "email_attachment",
        "access_level": access_level,
        "sender": sender,
        "subject": subject,
        "date": date,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "attachment_path": saved_path,
    }


def _process_single_attachment(
    attachment: dict,
    message_id: str,
    meta: dict = None,
) -> dict | None:
    filename = attachment.get("filename", "")
    if not filename:
        return None

    raw_bytes = attachment.get("bytes", b"")
    if not raw_bytes and attachment.get("data"):
        raw_bytes = _safe_b64decode(attachment["data"])

    if not raw_bytes:
        print(f"[Attachment] Skipping {filename}: no data could be read.")
        return None

    if not is_allowed_file(filename):
        print(f"[Attachment] Skipping unsupported attachment type: {filename}")
        return None

    ext = (
        filename.rsplit(".", 1)[-1].lower()
        if "." in filename
        else ""
    )

    mailbox = (meta or {}).get("mailbox", "")

    # 1. Fingerprint the raw bytes BEFORE writing to disk, running OCR and
    #    embedding. The same attachment reaches every mailbox, so only the first
    #    copy is ever saved, extracted and embedded.
    byte_hash = attachment_fingerprint(raw_bytes)
    bytes_is_new, bytes_prior = claim(
        ATTACHMENT,
        byte_hash,
        mailbox=mailbox,
        message_id=message_id,
        filename=filename,
    )

    if not bytes_is_new:
        bytes_prior = bytes_prior or {}
        print(
            f"[ContentDedup] {filename}: identical attachment bytes already indexed as "
            f"doc '{bytes_prior.get('doc_id') or 'unknown'}' (first seen in "
            f"{bytes_prior.get('first_mailbox') or 'unknown mailbox'}); "
            "skipping save/extract/embed."
        )
        return None

    # 2. Persist the raw attachment file to permanent storage folder once.
    saved_path = save_file(raw_bytes, filename)
    print(f"[Attachment] Saved {filename} to {saved_path}")

    # 3. Check OCR cache or extract text. The OCR cache is keyed by the same
    #    content hash used for the ledger, so both agree on what "this attachment" is.
    content_hash = byte_hash
    cached_text = get_cached_ocr_result(content_hash)

    if cached_text is not None:
        extracted_text = cached_text
    else:
        try:
            extracted_text = load_document(saved_path)
            if not extracted_text or not extracted_text.strip():
                print(f"[Attachment] No text could be extracted from {filename}")
                return None

            if attachment_required_ocr(saved_path, ext):
                store_ocr_result(content_hash, extracted_text)

        except Exception as exc:
            print(f"[Attachment] Extraction error for {filename}: {exc}")
            return None

    # 4. Second gate: the same document re-published with different file bytes
    #    (re-saved PDF, renamed copy) still extracts to the same text.
    text_hash = body_fingerprint(extracted_text)
    text_is_new, text_prior = claim(
        ATTACHMENT_TEXT,
        text_hash,
        mailbox=mailbox,
        message_id=message_id,
        filename=filename,
    )

    if not text_is_new:
        text_prior = text_prior or {}
        print(
            f"[ContentDedup] {filename}: identical text already indexed as doc "
            f"'{text_prior.get('doc_id') or 'unknown'}'; skipping embed."
        )
        return None

    # 5. Build attachment record matching manual uploads
    record = _build_attachment_record(
        extracted_text=extracted_text,
        filename=filename,
        doc_id=f"{message_id}:{filename}",
        saved_path=saved_path,
        meta=meta,
    )
    record["_content_fingerprints"] = [
        (ATTACHMENT, byte_hash),
        (ATTACHMENT_TEXT, text_hash),
    ]
    return record


def _extract_body(message: dict) -> str:
    """
    Pull text from Gmail's nested MIME payload.

    Prefer text/plain. If no usable plain-text body exists,
    fall back to text/html.
    """
    payload = message.get("payload", {})

    plain_text = _extract_mime_part(
        payload,
        "text/plain",
    )

    if plain_text.strip():
        return plain_text

    html_text = _extract_mime_part(
        payload,
        "text/html",
    )

    if html_text.strip():
        return _html_to_text(html_text)

    return ""


def _extract_mime_part(
    payload: dict,
    mime_type: str,
) -> str:
    """
    Recursively find and decode the first requested MIME part.
    """
    if payload.get("mimeType") == mime_type:
        data = payload.get("body", {}).get("data", "")
        if data:
            try:
                decoded = _safe_b64decode(data)
                return decoded.decode("utf-8", errors="ignore")
            except Exception:
                return ""

    for part in payload.get("parts", []):
        result = _extract_mime_part(
            part,
            mime_type,
        )
        if result:
            return result

    return ""


def _html_to_text(html: str) -> str:
    """
    Convert HTML body content into plain text.
    """
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()

    return " ".join(
        parser.get_text().split()
    )


def _get_attachments(
    message: dict,
    gmail=None,
) -> list[dict]:
    """
    Returns:
        [{filename, data, bytes}]
    for every attachment part in the message.
    """
    attachments = []
    message_id = message.get("id")
    payload = message.get("payload", {})

    def _walk_parts(parts):
        for part in parts:
            filename = part.get("filename", "")

            # If filename not directly on part, check Content-Disposition or Content-Type headers
            if not filename:
                for header in part.get("headers", []):
                    h_name = header.get("name", "").lower()
                    if h_name in ("content-disposition", "content-type"):
                        val = header.get("value", "")
                        match = re.search(r'filename=["\']?([^"\';]+)["\']?', val, re.IGNORECASE)
                        if match:
                            filename = match.group(1).strip()
                            break

            body = part.get("body", {})
            attachment_id = body.get("attachmentId")
            inline_data = body.get("data")

            # Check if this part has an attachment or file data
            if filename and (attachment_id or inline_data):
                raw_bytes = b""

                if inline_data:
                    raw_bytes = _safe_b64decode(inline_data)

                if not raw_bytes and attachment_id and gmail and message_id:
                    try:
                        acquire_token(bucket="gmail_api")
                        att_res = (
                            gmail.users()
                            .messages()
                            .attachments()
                            .get(
                                userId="me",
                                messageId=message_id,
                                id=attachment_id,
                            )
                            .execute()
                        )

                        att_data = att_res.get("data", "")
                        if att_data:
                            raw_bytes = _safe_b64decode(att_data)

                    except Exception as exc:
                        print(
                            f"[Attachment] Failed to fetch attachment "
                            f"{attachment_id} ({filename}) for msg "
                            f"{message_id}: {exc}"
                        )

                if raw_bytes:
                    attachments.append(
                        {
                            "filename": filename,
                            "data": inline_data or "",
                            "bytes": raw_bytes,
                            "attachmentId": attachment_id,
                        }
                    )
                else:
                    print(
                        f"[Attachment] Warning: attachment {filename} "
                        f"in msg {message_id} could not be retrieved."
                    )

            if "parts" in part:
                _walk_parts(part["parts"])

    _walk_parts(
        payload.get("parts", [payload])
    )

    return attachments