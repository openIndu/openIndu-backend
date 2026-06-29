"""Chat session CRUD — list / create / rename / delete user sessions.

GET    /api/v1/chat/sessions              -> list sessions (newest first)
POST   /api/v1/chat/sessions              -> create session
PATCH  /api/v1/chat/sessions/{id}         -> rename session
DELETE /api/v1/chat/sessions/{id}         -> delete session + messages
GET    /api/v1/chat/sessions/{id}/messages -> load messages
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_member
from app.core.utils import ok
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.user import User

router = APIRouter()


def _get_session_or_404(session_id: int, user_id: int, db: Session) -> ChatSession:
    s = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == user_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    return s


@router.get("/chat/sessions")
def list_sessions(
    current_user: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id)
        .order_by(desc(ChatSession.updated_at))
        .all()
    )
    return ok([s.to_dict() for s in sessions])


@router.post("/chat/sessions")
def create_session(
    current_user: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    s = ChatSession(user_id=current_user.id, title="新会话")
    db.add(s)
    db.commit()
    db.refresh(s)
    return ok(s.to_dict())


class RenameBody(BaseModel):
    title: str


@router.patch("/chat/sessions/{session_id}")
def rename_session(
    session_id: int,
    body: RenameBody,
    current_user: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    title = body.title.strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    s = _get_session_or_404(session_id, current_user.id, db)
    s.title = title
    db.commit()
    db.refresh(s)
    return ok(s.to_dict())


@router.delete("/chat/sessions/{session_id}")
def delete_session(
    session_id: int,
    current_user: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    s = _get_session_or_404(session_id, current_user.id, db)
    db.delete(s)
    db.commit()
    return ok({"id": session_id})


@router.get("/chat/sessions/{session_id}/messages")
def get_messages(
    session_id: int,
    current_user: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    _get_session_or_404(session_id, current_user.id, db)
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
        .all()
    )
    return ok([m.to_dict() for m in msgs])
