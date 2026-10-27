from fastapi import APIRouter, BackgroundTasks, HTTPException
from schemas.website import WebsiteCrawlRequest, WebsiteCrawlResponse
from services.website_processing import extract_from_website

router = APIRouter(prefix="/website", tags=["Website"])


@router.post("/crawl", response_model=WebsiteCrawlResponse)
async def crawl_website(request: WebsiteCrawlRequest, background_tasks: BackgroundTasks):
    url = request.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="Invalid URL. Must begin with http:// or https://",
        )

    # Run in background so client request does not timeout during multi-page crawl
    background_tasks.add_task(extract_from_website, url)

    return WebsiteCrawlResponse(
        message=f"Website crawl and ingestion started for '{url}'. Web pages and linked PDFs will be saved to PostgreSQL and local storage, and indexed to Pinecone on-demand.",
        url=url,
        status="started",
    )
