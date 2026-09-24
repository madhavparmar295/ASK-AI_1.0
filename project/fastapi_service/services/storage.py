import os
import uuid

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "../storage/uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".xlsx",
    ".xls",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".bmp",
}


def is_allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def save_file(contents: bytes, filename: str) -> str:
    unique_name = f"{uuid.uuid4()}_{filename}"
    path = os.path.join(UPLOAD_DIR, unique_name)

    with open(path, "wb") as f:
        f.write(contents)

    return path
