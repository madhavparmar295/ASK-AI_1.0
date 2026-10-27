from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON
from database import Base


class ChatSession(Base):
    """Stores full conversation history sessions for a user."""
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, index=True)
    user_email = Column(String, index=True, nullable=False)
    title = Column(String, default="New Conversation")
    messages = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "session_id": self.id,
            "id": self.id,
            "title": self.title,
            "messages": self.messages or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
