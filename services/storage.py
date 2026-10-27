import os
import uuid

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_STORAGE = os.path.join(BASE_DIR, "storage", "uploads")

env_upload_dir = os.getenv("UPLOAD_DIR")
if not env_upload_dir or env_upload_dir in ("../storage/uploads", "storage/uploads"):
    UPLOAD_DIR = _DEFAULT_STORAGE
elif not os.path.isabs(env_upload_dir):
    UPLOAD_DIR = os.path.abspath(os.path.join(BASE_DIR, env_upload_dir))
else:
    UPLOAD_DIR = os.path.abspath(env_upload_dir)

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
    clean_filename = os.path.basename(filename)
    unique_name = f"{uuid.uuid4()}_{clean_filename}"
    path = os.path.abspath(os.path.join(UPLOAD_DIR, unique_name))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(contents)

    return path
