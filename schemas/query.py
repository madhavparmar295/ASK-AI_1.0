from typing import Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_email: str
    # Optional: when supplied, recent turns are used to interpret follow-up questions.
    session_id: Optional[str] = None


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
    filename: Optional[str] = None


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceChunk]

    # Whether the answer cited at least one retrieved source. An ungrounded answer is
    # still returned, but the client can show it as unsupported.
    grounded: bool = False
    # 1-based indexes into `sources` that the answer actually cited.
    cited_sources: list[int] = []
    cached: bool = False
    answer_latency_ms: Optional[float] = None
    session_id: Optional[str] = None
