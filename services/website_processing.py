import asyncio
import concurrent.futures
from datetime import datetime, timezone
import os
import sys
from urllib.parse import urlparse

from services.document_loader import load_document
from services.ingest import ingest_record
from services.pii import apply_pii_protection
from services.storage import is_allowed_file, save_file
from services.website_extract import extract_content, find_pdf_links
from services.website_fetch import fetch_bytes, fetch_page
from services.website_frontier import build_frontier


def _run_async(coro):
    """Safely run an async coroutine whether or not an event loop is already running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def extract_from_website(domain: str) -> list[dict]:
    """
    Crawls a website starting from domain/URL:
    1. Discovers internal URLs via sitemap and homepage links.
    2. Extracts clean text from each HTML page and ingests it into PostgreSQL
       (pinecone_indexed = False) for on-demand Pinecone indexing.
    3. Detects any linked PDFs, downloads and stores them in local storage/,
       then ingests their metadata into PostgreSQL (pinecone_indexed = False).
    """
    print(f"[Website] Starting ingestion for: {domain}")

    urls = build_frontier(domain)
    print(f"[Website] Discovered {len(urls)} URLs")

    records = []
    seen_pdfs = set()

    for index, url in enumerate(urls, start=1):
        print(f"\n[Website] Processing {index}/{len(urls)}: {url}")

        try:
            page_records = _process_single_page(url, seen_pdfs=seen_pdfs)
            for rec in page_records:
                records.append(rec)

        except Exception as e:
            print(f"[Website] Failed processing: {url}")
            print(f"[Website] Error: {type(e).__name__}: {e}")

    print("\n" + "=" * 80)
    print(f"[Website] Ingestion complete: {len(records)} total records saved to PostgreSQL.")
    print("=" * 80)
    return records


def _process_single_page(url: str, seen_pdfs: set = None) -> list[dict]:
    """Fetch one HTML page, ingest it into Postgres, and process any linked PDFs."""
    if seen_pdfs is None:
        seen_pdfs = set()

    results = []
    fetch_result = _run_async(fetch_page(url))

    if not fetch_result:
        print(f"[Website] Skipping page because fetch failed: {url}")
        return results

    html = fetch_result.get("html")
    if not html:
        print(f"[Website] Skipping page because HTML is empty: {url}")
        return results

    extracted = extract_content(html, url)
    if not extracted:
        print(f"[Website] No extractable content: {url}")
        return results

    raw_text = extracted.get("text", "").strip()
    title = extracted.get("title", url)

    if not raw_text:
        print(f"[Website] Empty extracted text: {url}")
        return results

    # 1. Build and ingest the Webpage Record (stored directly in Postgres content column)
    protected_text = apply_pii_protection(raw_text)
    header_prefix = f"[Title: {title} | URL: {url}]\n"
    full_text = header_prefix + protected_text

    page_record = {
        "doc_id": url,
        "filename": title,
        "source": url,
        "source_type": "website",
        "access_level": "public",
        "sender": None,
        "subject": None,
        "date": None,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "text": full_text,  # Stored in postgres content column
        "embed_text": full_text,  # Used for 384-d Stage-1 vector
        "attachment_path": None,  # No disk file
    }

    try:
        ingest_record(page_record)
        print(f"[Website -> Postgres] Ingested page: '{title}' ({url})")
        results.append(page_record)
    except Exception as exc:
        print(f"[Website -> Postgres] Failed to ingest page {url}: {exc}")

    # 2. Check for PDF links on this page
    pdf_links = find_pdf_links(html, url)
    if pdf_links:
        for pdf_url in pdf_links:
            if pdf_url in seen_pdfs:
                continue
            seen_pdfs.add(pdf_url)

            pdf_rec = _process_website_pdf(pdf_url, parent_page_url=url)
            if pdf_rec:
                results.append(pdf_rec)

    return results


def _process_website_pdf(pdf_url: str, parent_page_url: str) -> dict | None:
    """Download a PDF from the website, save it to local storage, and index metadata in Postgres."""
    print(f"[Website PDF] Found document link: {pdf_url}")

    parsed = urlparse(pdf_url)
    filename = os.path.basename(parsed.path) or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    if not is_allowed_file(filename):
        print(f"[Website PDF] Unsupported file type: {filename}")
        return None

    # Download PDF bytes
    pdf_bytes = _run_async(fetch_bytes(pdf_url))
    if not pdf_bytes:
        print(f"[Website PDF] Could not download {pdf_url}")
        return None

    try:
        # Save raw PDF to local permanent storage
        saved_path = save_file(pdf_bytes, filename)
        print(f"[Website PDF] Saved to local disk: {saved_path}")

        # Extract text to generate the 384-d document vector for Stage-1 search
        extracted_text = load_document(saved_path)
        if not extracted_text or not extracted_text.strip():
            print(f"[Website PDF] No text could be extracted from {filename}")
            return None

        protected_text = apply_pii_protection(extracted_text)
        header_prefix = f"[Source URL: {pdf_url} | Linked From: {parent_page_url} | File: {filename}]\n"

        pdf_record = {
            "doc_id": pdf_url,
            "filename": filename,
            "source": pdf_url,
            "source_type": "website_pdf",
            "access_level": "public",
            "sender": None,
            "subject": None,
            "date": None,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            # Content column in Postgres is kept empty, just like email attachments & manual uploads
            "text": "",
            "embed_text": header_prefix + protected_text,
            "attachment_path": saved_path,
        }

        ingest_record(pdf_record)
        print(f"[Website PDF -> Postgres] Ingested document metadata: '{filename}'")
        return pdf_record

    except Exception as exc:
        print(f"[Website PDF] Error processing {pdf_url}: {exc}")
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  python -m services.website_processing <website_url>\n\n"
            "Example:\n"
            "  python -m services.website_processing https://iitj.ac.in"
        )
        sys.exit(1)

    domain = sys.argv[1]
    records = extract_from_website(domain)

    print("\n" + "=" * 80)
    print(f"Summary: {len(records)} records ingested into PostgreSQL.")
    print("When users ask questions, these pages and documents will be indexed into Pinecone on demand.")
    print("=" * 80)