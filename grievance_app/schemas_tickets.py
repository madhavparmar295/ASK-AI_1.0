import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _clean(v: str) -> str:
    return v.replace("\x00", "").strip()


class IssueCreate(BaseModel):
    description: str = Field(min_length=5, max_length=5000)
    category_id: uuid.UUID
    unit_id: Optional[uuid.UUID] = None
    location_text: Optional[str] = Field(default=None, max_length=300)
    confidential: bool = False

    @field_validator("description", "location_text")
    @classmethod
    def clean(cls, v):
        return _clean(v) if isinstance(v, str) else v

    @field_validator("description")
    @classmethod
    def not_blank(cls, v):
        if len(v) < 5:
            raise ValueError("Please describe the problem")
        return v


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def clean(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("Text cannot be empty")
        return v


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("A reason is required")
        return v


class OptionalReasonIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def clean(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("A note is required")
        return v


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=2000)


class ReassignIn(BaseModel):
    assignee_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=500)


# ---------- output ----------

class IdName(BaseModel):
    id: uuid.UUID
    name: str


class ReporterOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    department: Optional[str] = None
    hostel: Optional[str] = None
    room: Optional[str] = None


class AttachmentOut(BaseModel):
    id: uuid.UUID
    original_name: str
    mime_type: str
    size_bytes: int
    scan_status: str
    uploaded_by_me: bool = False
    created_at: datetime


class EventOut(BaseModel):
    type: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    text: Optional[str] = None
    actor: str
    created_at: datetime
    internal: Optional[bool] = None   # only shown to staff


class FeedbackOut(BaseModel):
    rating: int
    comment: Optional[str] = None


class TicketListItem(BaseModel):
    id: uuid.UUID
    ticket_no: str
    status: str
    title: str
    category: IdName
    unit: Optional[IdName] = None
    assignee: Optional[IdName] = None
    reporter_name: Optional[str] = None     # staff views only
    escalation_level: int
    due_at: Optional[datetime] = None
    overdue: bool = False
    confidential: bool
    urgent: bool
    created_at: datetime


class TicketPage(BaseModel):
    items: list[TicketListItem]
    total: int
    limit: int
    offset: int


class TicketDetail(BaseModel):
    id: uuid.UUID
    ticket_no: str
    status: str
    category: IdName
    unit: Optional[IdName] = None
    location_text: Optional[str] = None
    description: str
    confidential: bool
    urgent: bool
    escalation_level: int
    due_at: Optional[datetime] = None
    overdue: bool = False
    assignee: Optional[IdName] = None
    reporter: Optional[ReporterOut] = None   # hidden from the reporter themselves
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    attachments: list[AttachmentOut]
    events: list[EventOut]
    actions: list[str]
    feedback: Optional[FeedbackOut] = None
