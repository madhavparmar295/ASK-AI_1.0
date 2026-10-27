"""File uploads (task T11).

Rules: JPG, PNG and PDF only (checked from the file's first bytes, never the name);
max size and count from settings; random stored name; stored outside the web root;
the content is never changed (images are stored exactly as uploaded).
"""
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..constants import Status
from ..models import Attachment, Ticket, User
from ..permissions import can_handle
from .errors import ServiceError
from .scan import scan_file
from .tickets import add_event, utcnow

SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"%PDF-", "application/pdf", ".pdf"),
]
CHUNK = 64 * 1024


def detect_type(header: bytes) -> Optional[tuple[str, str]]:
    for magic, mime, ext in SIGNATURES:
        if header.startswith(magic):
            return mime, ext
    return None


def clean_name(name: Optional[str]) -> str:
    """Display name only: no path parts, no control characters, limited length."""
    name = (name or "file").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return (name or "file")[:150]


def download_name(original: str, mime: str) -> str:
    ext = {m: e for _, m, e in SIGNATURES}[mime]
    stem = os.path.splitext(original)[0] or "file"
    return stem[:100] + ext


def save_upload(db: Session, user: User, ticket: Ticket, fileobj: BinaryIO, filename: Optional[str],
                now: Optional[datetime] = None) -> Attachment:
    now = now or utcnow()
    s = get_settings()
    if not (user.id == ticket.reporter_id or can_handle(user, ticket)):
        raise ServiceError(403, "You cannot add files to this ticket")
    if ticket.status in Status.FINAL:
        raise ServiceError(409, "This ticket is closed")
    existing = db.scalar(select(func.count()).select_from(Attachment)
                         .where(Attachment.ticket_id == ticket.id, Attachment.uploaded_by == user.id)) or 0
    if existing >= s.max_attachments_per_user_per_ticket:
        raise ServiceError(409, f"At most {s.max_attachments_per_user_per_ticket} files can be added")

    header = fileobj.read(16)
    kind = detect_type(header)
    if kind is None:
        raise ServiceError(415, "Only JPG, PNG and PDF files are accepted")
    mime, ext = kind

    folder = Path(s.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = secrets.token_hex(16) + ext
    final_path = folder / stored_name
    tmp_path = folder / (stored_name + ".part")
    limit = s.max_upload_mb * 1024 * 1024
    size = 0
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            chunk = header
            while chunk:
                size += len(chunk)
                if size > limit:
                    raise ServiceError(413, f"File is larger than {s.max_upload_mb} MB")
                out.write(chunk)
                chunk = fileobj.read(CHUNK)
        if size == 0:
            raise ServiceError(422, "The file is empty")
        verdict = scan_file(str(tmp_path))
        if verdict in ("infected", "scan_error"):
            raise ServiceError(422, "The file was rejected by the security scan")
        os.replace(tmp_path, final_path)
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    att = Attachment(ticket_id=ticket.id, uploaded_by=user.id, stored_name=stored_name,
                     original_name=clean_name(filename), mime_type=mime, size_bytes=size,
                     scan_status=verdict, created_at=now)
    db.add(att)
    add_event(db, ticket, "attachment", user, f"File added: {att.original_name}", visible_to_student=True, now=now)
    db.commit()
    return att


def file_path(att: Attachment) -> Path:
    return Path(get_settings().upload_dir) / att.stored_name
