import os

import fitz  # PyMuPDF — used only to detect scanned pages
from docx import Document
from pypdf import PdfReader
from services.ocr import ocr_image, ocr_pdf
from services.xlsx import extract_excel_text, extract_csv_text

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}


# ---------------------------------------------------------
# Individual parsers — one per file type
# ---------------------------------------------------------


def load_pdf(file_path: str) -> str:
    """Extract text from a PDF, page by page, and join it into one string."""
    reader = PdfReader(file_path)
    pages_text = []
    for page in reader.pages:
        pages_text.append(page.extract_text() or "")
    return "\n".join(pages_text)


def load_docx(file_path: str) -> str:
    """Extract text from a DOCX, paragraph by paragraph, and join it into one string."""
    doc = Document(file_path)
    paragraphs_text = [para.text for para in doc.paragraphs]
    return "\n".join(paragraphs_text)


def load_txt(file_path: str) -> str:
    """Read a plain text file using UTF-8 encoding."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------
# Scanned-PDF detection
# ---------------------------------------------------------


def is_scanned_pdf(pdf_path: str, min_chars_per_page: int = 20) -> bool:
    """
    Heuristic: if every page has almost no extractable text,
    the PDF is image-only (scanned) rather than a real text PDF.
    Returns False as soon as one page has real text.
    """
    doc = fitz.open(pdf_path)
    for page in doc:
        if len(page.get_text().strip()) >= min_chars_per_page:
            return False  # found a page with real text -> not scanned
    return True  # every page was empty -> treat as scanned


# ---------------------------------------------------------
# Dispatcher — routes to the correct parser based on extension
# ---------------------------------------------------------


def load_document(file_path: str) -> str:
    """
    Look at the file extension and call the matching parser.
    Images and scanned PDFs are routed through OCR.
    Always returns a plain text string, regardless of input format.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in SUPPORTED_IMAGE_EXTENSIONS:
        return ocr_image(file_path)

    if ext == ".pdf":
        if is_scanned_pdf(file_path):
            return ocr_pdf(file_path)
        return load_pdf(file_path)

    if ext == ".docx":
        return load_docx(file_path)

    if ext == ".txt":
        return load_txt(file_path)

    if ext in {".xlsx", ".xls"}:
        return extract_excel_text(file_path)

    if ext == ".csv":
        return extract_csv_text(file_path)

    raise ValueError(f"Unsupported file type: {ext}")
