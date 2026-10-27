"""
Answer feedback: thumbs up/down plus an optional comment and the sources used.

Stored in the database and logged as a structured event, so a quality drop is
visible both as a log line and as a reportable number.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models.feedback import AnswerFeedback
from services.logging_config import log_event

router = APIRouter(prefix="/feedback", tags=["Feedback"])
_logger = logging.getLogger("askai.feedback")


class FeedbackRequest(BaseModel):
    question: str = Field(..., min_length=1)
    rating: Literal["up", "down"]
    user_email: Optional[str] = None
    session_id: Optional[str] = None
    comment: Optional[str] = None
    answer_excerpt: Optional[str] = None
    sources: list[str] = []


@router.post("")
def submit_feedback(payload: FeedbackRequest, db: Session = Depends(get_db)):
    """Record a rating for an answer."""
    row = AnswerFeedback(
        user_email=(payload.user_email or "").lower().strip() or None,
        session_id=payload.session_id,
        question=payload.question[:2000],
        rating=payload.rating,
        comment=payload.comment[:2000] if payload.comment else None,
        answer_excerpt=payload.answer_excerpt[:2000] if payload.answer_excerpt else None,
        sources=payload.sources[:50],
    )

    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception as exc:
        db.rollback()
        log_event(_logger, "feedback_failed", level=logging.ERROR, error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="Feedback storage is unavailable.")

    log_event(
        _logger,
        "feedback",
        rating=payload.rating,
        question=payload.question[:200],
        sources=len(payload.sources),
        has_comment=bool(payload.comment),
        user_email=row.user_email,
    )

    return {"success": True, "id": row.id}


@router.get("/summary")
def feedback_summary(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Up/down counts and the most recent negative comments."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        rows = (
            db.query(AnswerFeedback.rating, func.count(AnswerFeedback.id))
            .filter(AnswerFeedback.created_at >= since)
            .group_by(AnswerFeedback.rating)
            .all()
        )
        downs = (
            db.query(AnswerFeedback)
            .filter(
                AnswerFeedback.created_at >= since,
                AnswerFeedback.rating == "down",
            )
            .order_by(AnswerFeedback.created_at.desc())
            .limit(20)
            .all()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Feedback storage is unavailable: {exc}")

    counts = {rating: count for rating, count in rows}
    up = counts.get("up", 0)
    down = counts.get("down", 0)
    total = up + down

    return {
        "window_days": days,
        "up": up,
        "down": down,
        "total": total,
        "satisfaction": round(up / total, 3) if total else None,
        "recent_negative": [
            {
                "question": row.question,
                "comment": row.comment,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in downs
        ],
    }
