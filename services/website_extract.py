from io import StringIO
from urllib.parse import urljoin

import pandas as pd
import trafilatura
from bs4 import BeautifulSoup


def extract_content(html: str, url: str):
    """
    Extract the main readable content from an HTML page.

    Returns:
        {
            "title": str,
            "text": str
        }
    """

    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Get page title
    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else url

    # Remove elements that usually contain navigation/noise
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    # Main article/page text using Trafilatura
    text = trafilatura.extract(
        str(soup),
        include_links=False,
        include_images=False,
        include_tables=True,
        favor_precision=True,
    )

    # Fallback if Trafilatura doesn't extract anything
    if not text:
        text = soup.get_text("\n", strip=True)

    # Extract HTML tables separately
    try:
        tables = pd.read_html(StringIO(html))

        if tables:
            table_text = []

            for table in tables:
                table_text.append(table.to_string(index=False))

            if table_text:
                text = (text or "") + "\n\n" + "\n\n".join(table_text)

    except Exception as e:
        print(f"[Website Extract] Table extraction skipped: {e}")

    if not text or not text.strip():
        return None

    return {
        "title": title,
        "text": text.strip(),
    }


def find_pdf_links(html: str, base_url: str):
    """
    Find PDF links present on a webpage.

    PDF files are only detected here.
    They are NOT downloaded or extracted yet.
    """

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    pdf_links = set()

    for link in soup.find_all("a", href=True):
        href = link["href"].strip()

        if not href:
            continue

        absolute_url = urljoin(base_url, href)

        if absolute_url.lower().split("?")[0].endswith(".pdf"):
            pdf_links.add(absolute_url)

    return sorted(pdf_links)
