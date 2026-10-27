from typing import Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.chat import ChatSession

router = APIRouter(prefix="/chat/api", tags=["Chat History"])


import uuid


class SaveSessionRequest(BaseModel):
    email: str
    session_id: Optional[str] = None
    title: Optional[str] = None
    messages: list[Any] = []


@router.get("/history/")
def get_history(email: str = Query(..., description="User email address"), db: Session = Depends(get_db)):
    """Fetches all saved chat sessions for the specified user."""
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_email == email.lower().strip())
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return {"sessions": [s.to_dict() for s in sessions]}


@router.post("/save/")
def save_session(payload: SaveSessionRequest, db: Session = Depends(get_db)):
    """Saves or updates a chat session for the user."""
    email = payload.email.lower().strip()
    session_id = payload.session_id.strip() if payload.session_id else None

    # Derive smart title from first user message if not supplied
    title = payload.title
    if (not title or title == "New Conversation") and payload.messages:
        first_msg = payload.messages[0]
        text_content = first_msg.get("content") or first_msg.get("text") or ""
        if text_content:
            title = text_content[:35] + ("..." if len(text_content) > 35 else "")

    if not title:
        title = "New Conversation"

    session = None
    if session_id:
        session = (
            db.query(ChatSession)
            .filter(ChatSession.id == session_id, ChatSession.user_email == email)
            .first()
        )

    if session:
        session.title = title
        session.messages = payload.messages
    else:
        new_id = session_id or str(uuid.uuid4())
        session = ChatSession(
            id=new_id,
            user_email=email,
            title=title,
            messages=payload.messages,
        )
        db.add(session)

    db.commit()
    db.refresh(session)
    return {"success": True, "session_id": session.id, "session": session.to_dict()}


@router.post("/session/{session_id}/")
def delete_session(session_id: str, email: str = Query(..., description="User email"), db: Session = Depends(get_db)):
    """Deletes a specific chat session."""
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_email == email.lower().strip())
        .first()
    )
    if session:
        db.delete(session)
        db.commit()
    return {"success": True}


@router.post("/clear/")
def clear_history(email: str = Query(..., description="User email"), db: Session = Depends(get_db)):
    """Clears all chat sessions for the specified user."""
    db.query(ChatSession).filter(ChatSession.user_email == email.lower().strip()).delete()
    db.commit()
    return {"success": True}
