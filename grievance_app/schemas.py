import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    role: str
    department: Optional[str] = None
    hostel: Optional[str] = None
    room: Optional[str] = None
    is_head: bool = False          # level 1 or 2 anywhere in the routing table
    csrf_token: Optional[str] = None


class GoogleLoginIn(BaseModel):
    credential: str


class DevLoginIn(BaseModel):
    email: str


class DevUserOut(BaseModel):
    email: str
    name: str
    role: str
