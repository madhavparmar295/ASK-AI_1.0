from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, JSON, String

from database import Base


class AnswerFeedback(Base):
    """
    One row per thumbs up/down on an answer.

    Rows are how quality regressions get noticed: a drop in the up-rate for a
    question pattern is the signal to look at the retrieval logs for it.
    """

    __tablename__ = "answer_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_email = Column(String, index=True, nullable=True)
    session_id = Column(String, index=True, nullable=True)
    question = Column(String, nullable=False)
    rating = Column(String, nullable=False, index=True)  # "up" or "down"
    comment = Column(String, nullable=True)
    answer_excerpt = Column(String, nullable=True)
    sources = Column(JSON, default=list)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_email": self.user_email,
            "session_id": self.session_id,
            "question": self.question,
            "rating": self.rating,
            "comment": self.comment,
            "sources": self.sources or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
