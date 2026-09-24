import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile
from schemas.document import DocumentResponse
from services.access_control import classify_access_level
from services.document_loader import load_document
from services.ingest import ingest_record
from services.storage import is_allowed_file, save_file

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentResponse)
async def upload_file(file: UploadFile):

    if not is_allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    contents = await file.read()

    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # 3. Save file to local storage
    file_path = save_file(contents, file.filename)

    # 4. Parse document
    text = load_document(file_path)

    if not text.strip():
        raise HTTPException(status_code=400, detail="No text could be extracted from the document.")

    # Create a unique tracking ID for this document
    doc_id = str(uuid.uuid4())

    record = {
        "text": text,
        "doc_id": doc_id,
        "access_level": classify_access_level(text),
        "source_type": "document_upload",
        "source": file.filename,
        "filename": file.filename,
        "uploaded_at": datetime.utcnow().isoformat(),
    }
    ingest_record(record)

    return DocumentResponse(filename=file.filename, path=file_path, uploaded_at=datetime.utcnow())
