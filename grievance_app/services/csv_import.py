import csv
import io

from fastapi import UploadFile

from .errors import ServiceError

MAX_BYTES = 1024 * 1024
MAX_ROWS = 5000


def read_csv(upload: UploadFile, required: list[str]) -> list[dict]:
    """Read an uploaded CSV into a list of dicts with lower-case, stripped headers and values."""
    raw = upload.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ServiceError(413, "The CSV file is larger than 1 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ServiceError(422, "The file must be a UTF-8 CSV (in Excel: Save as CSV UTF-8)")
    reader = csv.DictReader(io.StringIO(text))
    headers = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in headers]
    if missing:
        raise ServiceError(422, f"Missing column(s): {', '.join(missing)}. Download the template to see the format.")
    rows = []
    for r in reader:
        rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in r.items() if k is not None})
        if len(rows) > MAX_ROWS:
            raise ServiceError(413, f"At most {MAX_ROWS} rows per file")
    return rows
