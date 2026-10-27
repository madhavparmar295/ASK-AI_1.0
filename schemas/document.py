from datetime import datetime

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    filename: str
    path: str
    uploaded_at: datetime
