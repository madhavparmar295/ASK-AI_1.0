from bs4 import BeautifulSoup
from urllib.parse import urljoin


def find_pdf_links(html: str, base_url: str) -> list[str]:
    """Find every PDF link on a page -- this part works today, no dependency issue."""
    soup = BeautifulSoup(html, "html.parser")
    return [
        urljoin(base_url, a["href"])
        for a in soup.find_all("a", href=True)
        if a["href"].lower().endswith(".pdf")
    ]


def handle_website_pdf(url: str, content: bytes) -> dict:
    """
    TEMPORARY STUB.
    Real implementation once attachment_processor.py exists again:
    write `content` to a tempfile (same pattern email_processing.py
    already uses), then call process_attachment(temp_path, "pdf").
    """
    print(f"[STUB] would process PDF at {url} ({len(content)} bytes)")
    return {"text": "", "low_content": True, "title": url}
