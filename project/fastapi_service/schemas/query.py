from typing import Optional
from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str
    user_email: str


class SourceChunk(BaseModel):
    text: str
    score: float
    doc_id: str
    access_level: str
    sender: Optional[str] = None
    subject: Optional[str] = None
    date: Optional[str] = None
    source: Optional[str] = None
    source_type: Optional[str] = None


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceChunk]
