"""
Content-level deduplication ledger (Redis backed).

College broadcasts land in many mailboxes, so the same message body and the same
attachment arrive repeatedly. Before any extraction, disk write, embedding or
Pinecone upsert, callers claim a *content fingerprint* here::

    is_new, prior = claim(BODY, body_fingerprint(raw_body), mailbox=..., message_id=...)
    if not is_new:
        # already stored, extracted and embedded from another mailbox
        # -> skip entirely, the origin is recorded for rebuilds
        return

Fingerprints
    body            sha256 of the NORMALIZED body text (per-recipient greeting,
                    tracking links, quoted replies and signatures stripped), so the
                    same broadcast fingerprints identically across mailboxes.
    attachment      sha256 of the raw attachment BYTES (never the filename).
    attachment_text sha256 of the NORMALIZED extracted text, which catches the same
                    document re-published with different file bytes.

Design rules
    1. A fingerprint mismatch must never lose content. Normalization errs towards
       too strict, so an un-deduped duplicate is the worst case, not a dropped notice.
    2. Fails OPEN. If Redis is unreachable every claim reports "new", so ingestion
       behaves exactly as it did before this module existed. Dedup is an
       optimisation, never a correctness requirement for ingestion.
    3. A claim that never completes (worker died, Pinecone error) is reclaimable
       after CLAIM_STALE_AFTER_SECONDS, so content cannot get stuck as "pending"
       forever.
"""

import hashlib
import json
import os
import re
import time
import unicodedata

from dotenv import load_dotenv

load_dotenv()

# Redis is already provisioned for Celery; reuse it unless an explicit URL is given.
REDIS_URL = os.getenv("DEDUP_REDIS_URL") or os.getenv("CELERY_BROKER_URL")
PREFIX = os.getenv("CONTENT_DEDUP_PREFIX", "askai:content_dedup")
CLAIM_STALE_AFTER_SECONDS = int(os.getenv("CONTENT_DEDUP_STALE_SECONDS", "3600"))

BODY = "body"
ATTACHMENT = "attachment"
ATTACHMENT_TEXT = "attachment_text"

STATUS_PENDING = "pending"
STATUS_INDEXED = "indexed"

_client = None
_redis_offline = False

_URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
# Unambiguous markers of quoted/forwarded history. A bare "From:" line is
# deliberately NOT a marker: truncating on it could collapse two different mails
# into one fingerprint, which would silently drop content.
_QUOTE_MARKER_RE = re.compile(
    r"^\s*(on .{0,80}\bwrote:|-{2,}\s*original message\s*-{2,}|_{5,}\s*$)",
    re.IGNORECASE | re.MULTILINE,
)
_SIGNATURE_RE = re.compile(r"^\s*--\s*$", re.MULTILINE)
_GREETING_RE = re.compile(r"^\s*(dear|hi|hello|respected|greetings)[^\n]{0,60},?\s*$", re.IGNORECASE)

_HTML_ENTITIES = (
    ("&nbsp;", " "),
    ("&amp;", "&"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&quot;", '"'),
    ("&#39;", "'"),
    ("&rsquo;", "'"),
    ("&lsquo;", "'"),
    ("&ldquo;", '"'),
    ("&rdquo;", '"'),
    ("&mdash;", "-"),
    ("&ndash;", "-"),
)


def get_redis():
    """Return a shared Redis client, or None when Redis is unavailable."""
    global _client, _redis_offline

    if _client is not None:
        return _client
    if _redis_offline or not REDIS_URL:
        return None

    try:
        import redis

        client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        client.ping()
        _client = client
    except Exception as exc:  # pragma: no cover - depends on environment
        print(f"[ContentDedup] Redis unavailable ({exc}); content dedup disabled for this process.")
        _client = None
        _redis_offline = True

    return _client


def normalize_body(text: str) -> str:
    """
    Reduce a message body or an extracted document to a comparable form.

    Strips HTML markup, entities, per-recipient greetings, URLs (tracking links
    carry per-recipient tokens), quoted reply history, signature blocks and
    whitespace/case differences.
    """
    if not text:
        return ""

    cleaned = unicodedata.normalize("NFKC", text)

    if "<" in cleaned and ">" in cleaned:
        cleaned = _TAG_RE.sub(" ", cleaned)
        for entity, replacement in _HTML_ENTITIES:
            cleaned = cleaned.replace(entity, replacement)

    marker = _QUOTE_MARKER_RE.search(cleaned)
    if marker:
        cleaned = cleaned[: marker.start()]

    signature = _SIGNATURE_RE.search(cleaned)
    if signature:
        cleaned = cleaned[: signature.start()]

    lines = cleaned.splitlines()
    kept = [line for index, line in enumerate(lines) if not (index < 5 and _GREETING_RE.match(line))]

    # Drop any line carrying a URL. Such lines are per-recipient boilerplate
    # ("View online: <tracking link>") and are re-wrapped differently by every mail
    # client. Dropping them can only cause a dedup miss, never lost content.
    kept = [line for line in kept if not _URL_RE.search(line)]

    cleaned = "\n".join(kept)

    # Collapse every whitespace run, including line breaks: the same notice gets
    # re-wrapped by different mail clients and by HTML -> text conversion, so line
    # positions must not influence the fingerprint.
    cleaned = re.sub(r"\s+", " ", cleaned)

    return cleaned.strip().casefold()


def body_fingerprint(raw_text: str) -> str:
    """Fingerprint for a body or extracted document text."""
    normalized = normalize_body(raw_text)
    digest = hashlib.sha256()
    digest.update(str(len(normalized)).encode("utf-8"))
    digest.update(b"|")
    digest.update(normalized.encode("utf-8"))
    return digest.hexdigest()


def attachment_fingerprint(raw_bytes: bytes) -> str:
    """Fingerprint for an attachment: raw bytes, never the filename."""
    return hashlib.sha256(raw_bytes).hexdigest()


def _record_key(kind: str, fingerprint: str) -> str:
    return f"{PREFIX}:{kind}:{fingerprint}"


def _origin_key(kind: str, fingerprint: str) -> str:
    return f"{PREFIX}:origins:{kind}:{fingerprint}"


def get_record(kind: str, fingerprint: str) -> dict | None:
    """Read a ledger record without claiming it."""
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.get(_record_key(kind, fingerprint))
    except Exception as exc:
        print(f"[ContentDedup] Lookup failed for {kind} ({exc}).")
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def claim(
    kind: str,
    fingerprint: str,
    mailbox: str = "",
    message_id: str = "",
    filename: str = "",
) -> tuple[bool, dict | None]:
    """
    Atomically claim a fingerprint.

    Returns (True, payload) when this caller is the first to see the content and
    should store/extract/embed it. Returns (False, prior_record) when the content
    was already seen, in which case the caller must not re-embed it.

    The origin (mailbox + message id) is recorded on both paths so a document can
    be traced back to every mailbox that received it.
    """
    client = get_redis()
    if client is None:
        return True, None

    now = time.time()
    payload = {
        "kind": kind,
        "fingerprint": fingerprint,
        "status": STATUS_PENDING,
        "first_seen": now,
        "first_mailbox": mailbox,
        "first_message_id": message_id,
    }
    if filename:
        payload["filename"] = filename

    try:
        created = client.set(_record_key(kind, fingerprint), json.dumps(payload), nx=True)
    except Exception as exc:
        print(f"[ContentDedup] Claim failed for {kind} ({exc}); treating content as new.")
        return True, None

    if created:
        record_origin(kind, fingerprint, mailbox, message_id)
        return True, payload

    prior = get_record(kind, fingerprint)
    record_origin(kind, fingerprint, mailbox, message_id)

    if prior is None:
        # The key exists but is unreadable/expired between calls: treat as new so
        # ingestion never stalls on a broken ledger entry.
        return True, None

    if (
        prior.get("status") == STATUS_PENDING
        and now - float(prior.get("first_seen") or 0) > CLAIM_STALE_AFTER_SECONDS
    ):
        # An earlier attempt died before marking the content indexed. Take over
        # rather than leaving it unusable forever.
        payload["taken_over_from"] = prior.get("first_seen")
        try:
            client.set(_record_key(kind, fingerprint), json.dumps(payload))
        except Exception:
            pass
        print(f"[ContentDedup] Reclaiming stale {kind} claim from {prior.get('first_mailbox') or 'unknown'}.")
        return True, payload

    return False, prior


def mark_indexed(kind: str, fingerprint: str, doc_id: str = "") -> None:
    """Record that the content is stored and embedded. Safe to call repeatedly."""
    client = get_redis()
    if client is None:
        return

    payload = get_record(kind, fingerprint) or {"kind": kind, "fingerprint": fingerprint}
    payload["status"] = STATUS_INDEXED
    payload["indexed_at"] = time.time()
    if doc_id:
        payload["doc_id"] = doc_id

    try:
        client.set(_record_key(kind, fingerprint), json.dumps(payload))
    except Exception as exc:
        print(f"[ContentDedup] Could not mark {kind} indexed ({exc}).")


def release(kind: str, fingerprint: str) -> None:
    """
    Drop a claim whose content never reached Pinecone.

    Called when storing/embedding failed, so the next mailbox delivering the same
    notice can retry it instead of being skipped by a permanently pending claim.
    Origins are preserved for traceability.
    """
    client = get_redis()
    if client is None:
        return
    try:
        client.delete(_record_key(kind, fingerprint))
    except Exception as exc:
        print(f"[ContentDedup] Could not release {kind} claim ({exc}).")


def record_origin(kind: str, fingerprint: str, mailbox: str, message_id: str, keep: int = 50) -> None:
    """Append (mailbox, message_id) to the fingerprint's origin list."""
    client = get_redis()
    if client is None or not mailbox and not message_id:
        return

    key = _origin_key(kind, fingerprint)
    entry = json.dumps({"mailbox": mailbox, "message_id": message_id, "seen_at": time.time()})
    try:
        pipe = client.pipeline()
        pipe.rpush(key, entry)
        pipe.ltrim(key, -keep, -1)
        pipe.execute()
    except Exception as exc:
        print(f"[ContentDedup] Could not record origin for {kind} ({exc}).")


def get_origins(kind: str, fingerprint: str) -> list[dict]:
    """Every mailbox/message that delivered this content, newest last."""
    client = get_redis()
    if client is None:
        return []
    try:
        entries = client.lrange(_origin_key(kind, fingerprint), 0, -1)
    except Exception:
        return []

    origins = []
    for entry in entries:
        try:
            origins.append(json.loads(entry))
        except (TypeError, ValueError):
            continue
    return origins
