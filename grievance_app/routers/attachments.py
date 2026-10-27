import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Attachment, Ticket, User
from ..permissions import can_download_attachment, get_ticket_or_404
from ..schemas_tickets import AttachmentOut
from ..security.deps import get_current_user
from ..services import attachments as svc

router = APIRouter(tags=["attachments"])


@router.post("/issues/{ticket_id}/attachments", response_model=AttachmentOut, status_code=201)
def upload(ticket_id: uuid.UUID, file: UploadFile = File(...), user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    ticket = get_ticket_or_404(db, user, ticket_id)
    att = svc.save_upload(db, user, ticket, file.file, file.filename)
    return AttachmentOut(id=att.id, original_name=att.original_name, mime_type=att.mime_type,
                         size_bytes=att.size_bytes, scan_status=att.scan_status,
                         uploaded_by_me=True, created_at=att.created_at)


@router.get("/attachments/{attachment_id}")
def download(attachment_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    att = db.get(Attachment, attachment_id)
    ticket = db.get(Ticket, att.ticket_id) if att else None
    if att is None or ticket is None or not can_download_attachment(user, ticket):
        raise HTTPException(status_code=404, detail="Not found")     # same answer for both cases
    path = svc.file_path(att)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        path, media_type=att.mime_type, filename=svc.download_name(att.original_name, att.mime_type),
        content_disposition_type="attachment",       # never shown inline in the browser
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
                 "Content-Security-Policy": "default-src 'none'; sandbox"})
