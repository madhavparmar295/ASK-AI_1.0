import asyncio
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


USER_AGENT = "ASK-AI-Website-Ingestion/1.0"


async def _fetch(url: str):
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            verify=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)

            print(
                f"[Frontier] {response.status_code} "
                f"{response.url}"
            )

            return response

    except Exception as e:
        print(f"[Frontier] Failed: {url}")
        print(f"[Frontier] Error: {e}")
        return None


def _normalize(url: str):
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return None

    # Remove fragments
    return parsed._replace(fragment="").geturl()


def _same_domain(url: str, domain: str):
    return urlparse(url).netloc.lower() == domain.lower()


async def _discover(start_url: str):
    start_url = _normalize(start_url)

    if not start_url:
        return []

    parsed = urlparse(start_url)
    domain = parsed.netloc

    discovered = {start_url}

    print(f"[Frontier] Starting URL: {start_url}")
    print(f"[Frontier] Domain: {domain}")

    # ---------------------------------------------------------
    # 1. Try sitemap.xml
    # ---------------------------------------------------------
    sitemap_url = urljoin(start_url, "/sitemap.xml")

    print(f"[Frontier] Checking sitemap: {sitemap_url}")

    response = await _fetch(sitemap_url)

    if response and response.status_code == 200:
        content_type = response.headers.get("content-type", "").lower()

        if "xml" in content_type or response.text.lstrip().startswith("<"):
            soup = BeautifulSoup(response.text, "xml")

            sitemap_urls = soup.find_all("loc")

            for loc in sitemap_urls:
                if not loc.text:
                    continue

                url = _normalize(loc.text.strip())

                if url and _same_domain(url, domain):
                    discovered.add(url)

            print(
                f"[Frontier] Sitemap URLs discovered: "
                f"{len(discovered)}"
            )

    # ---------------------------------------------------------
    # 2. Fetch homepage and discover internal links
    # ---------------------------------------------------------
    response = await _fetch(start_url)

    if response and response.status_code < 500:
        html = response.text

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()

            if not href:
                continue

            absolute_url = urljoin(start_url, href)
            url = _normalize(absolute_url)

            if url and _same_domain(url, domain):
                discovered.add(url)

        print(
            f"[Frontier] Homepage links discovered: "
            f"{len(discovered)}"
        )

    # Keep the first crawl manageable for testing.
    urls = list(discovered)[:100]

    return urls


def build_frontier(domain):
    """
    Synchronous wrapper used by website_processing.py.
    """
    return asyncio.run(_discover(domain))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(
            "Usage: python -m services.website_frontier "
            "https://iitj.ac.in"
        )
        sys.exit(1)

    urls = build_frontier(sys.argv[1])

    print("\n=== FRONTIER RESULT ===")
    print(f"Total URLs: {len(urls)}")

    for url in urls:
        print(url)
