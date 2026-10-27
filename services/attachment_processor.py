from services.document_loader import (  # your existing pipeline, untouched
    is_scanned_pdf,
    load_document,
)
from services.xlsx import extract_csv_text, extract_excel_text

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "tiff", "bmp"}
SPREADSHEET_EXTENSIONS = {"xlsx", "xls"}


def process_attachment(file_path: str, ext: str) -> str:
    """
    Dispatch by extension. PDFs and images go through your existing
    load_document() (which already decides scanned-vs-real PDF and
    routes to OCR internally). Spreadsheets get the new row-preserving
    extractor. Unsupported types raise ValueError -- caller skips
    that one attachment instead of failing the whole email.
    """
    ext = ext.lower()

    if ext in {"pdf"} | IMAGE_EXTENSIONS | {"docx", "txt"}:
        # note: load_document expects a real extension on the path itself
        return load_document(file_path)

    if ext in SPREADSHEET_EXTENSIONS:
        return extract_excel_text(file_path)

    if ext == "csv":
        return extract_csv_text(file_path)

    raise ValueError(f"No extraction handler for attachment type: {ext}")


def attachment_required_ocr(file_path: str, ext: str) -> bool:
    """Tells the caller whether OCR actually ran, so it knows whether to cache the result."""
    ext = ext.lower()
    if ext in IMAGE_EXTENSIONS:
        return True
    if ext == "pdf":
        return is_scanned_pdf(file_path)
    return False
