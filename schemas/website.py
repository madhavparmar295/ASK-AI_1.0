from pydantic import BaseModel


class WebsiteCrawlRequest(BaseModel):
    url: str


class WebsiteCrawlResponse(BaseModel):
    message: str
    url: str
    status: str
