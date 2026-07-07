"""Smart-consultation (RAG chat) API — member-facing, SSE streaming. §4.3.12

POST /api/v1/chat        -> SSE stream (event: sources / delta / done / error)
GET  /api/v1/chat/quota  -> remaining daily quota

Distinct from the MCP server (§4.4, serves external Claude Code): this endpoint
runs an in-process LLM (DeepSeek) over the same Milvus retrieval.
"""
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.dependencies import get_db, require_member
from app.core.utils import ok, real_client_ip
from app.models.chat_log import ChatLog
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.user import User
from app.services import chat_service

router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # 关闭 nginx/ingress 缓冲，保证逐 token 流式（见 §8 NFR / §4.3.12 部署注意）
    "X-Accel-Buffering": "no",
}


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatBody(BaseModel):
    message: str
    history: list[ChatTurn] | None = None
    filters: dict | None = None


def _today_count(db: Session, user_id: int) -> int:
    return (
        db.query(ChatLog)
        .filter(ChatLog.user_id == user_id, ChatLog.created_at >= date.today())
        .count()
    )


@router.get("/chat/quota")
async def chat_quota(
    current_user: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    if current_user.role == "admin":
        return ok({"limit": settings.CHAT_DAILY_LIMIT, "used": 0, "remaining": None, "unlimited": True})
    used = _today_count(db, current_user.id)
    return ok({
        "limit": settings.CHAT_DAILY_LIMIT,
        "used": used,
        "remaining": max(0, settings.CHAT_DAILY_LIMIT - used),
        "unlimited": False,
    })


@router.post("/chat")
async def chat(
    body: ChatBody,
    request: Request,
    current_user: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 1. 每日配额（admin 豁免），与下载限额同范式（§4.3.6-1）
    if current_user.role != "admin" and _today_count(db, current_user.id) >= settings.CHAT_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail=f"今日咨询次数已用完（{settings.CHAT_DAILY_LIMIT}次/天）")

    # 2. 检索（阻塞调用放线程池，避免卡事件循环）
    #    先用 LLM 将多轮对话改写为自包含搜索 query，再送入 Milvus
    history_dicts = [t.model_dump() for t in (body.history or [])]
    rewritten = await chat_service.rewrite_query(body.message, history_dicts)
    filters = {
        "brand": (body.filters or {}).get("brand"),
        "category": (body.filters or {}).get("category"),
    }
    try:
        chunks = await run_in_threadpool(
            chat_service.retrieve, rewritten, settings.RAG_TOP_K, filters
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="知识库暂不可用，请稍后再试") from exc
    sources = chat_service.sources_from(chunks)

    # 3. 记一条 chat_log（计入当日配额；token 用量在流结束后回填）
    log = ChatLog(
        user_id=current_user.id,
        ip_address=real_client_ip(request) or "unknown",
        question=body.message[:2000],
        source_docs=json.dumps([s["document_name"] for s in sources], ensure_ascii=False),
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # 4. SSE 流式返回（sources -> delta* -> done）
    return StreamingResponse(
        chat_service.stream_answer(body.message, history_dicts, chunks, sources, log.id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/chat/sessions/{session_id}/stream")
async def chat_session_stream(
    session_id: int,
    body: ChatBody,
    request: Request,
    current_user: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    # Validate session ownership
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id, ChatSession.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # Daily quota check (admin exempt)
    if current_user.role != "admin" and _today_count(db, current_user.id) >= settings.CHAT_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail=f"今日咨询次数已用完（{settings.CHAT_DAILY_LIMIT}次/天）")

    # Load history from DB (last 6 messages)
    db_msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.id))
        .limit(6)
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(db_msgs)]

    # Persist user message
    user_msg = ChatMessage(session_id=session_id, role="user", content=body.message[:4000])
    db.add(user_msg)
    # Auto-title from first user message
    if session.title == "新会话" and not db_msgs:
        session.title = body.message.strip()[:30]
    db.commit()

    # Retrieval — LLM rewrites the query first for cross-turn context
    rewritten = await chat_service.rewrite_query(body.message, history)
    filters = {
        "brand": (body.filters or {}).get("brand"),
        "category": (body.filters or {}).get("category"),
    }
    try:
        chunks = await run_in_threadpool(
            chat_service.retrieve, rewritten, settings.RAG_TOP_K, filters
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="知识库暂不可用，请稍后再试") from exc
    sources = chat_service.sources_from(chunks)

    # Quota log
    log = ChatLog(
        user_id=current_user.id,
        ip_address=real_client_ip(request) or "unknown",
        question=body.message[:2000],
        source_docs=json.dumps([s["document_name"] for s in sources], ensure_ascii=False),
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # Persist assistant message after stream completes
    async def stream_and_save():
        full_content = ""
        final_mode = None
        current_event = None
        async for chunk in chat_service.stream_answer(body.message, history, chunks, sources, log.id):
            text = chunk.decode() if isinstance(chunk, bytes) else chunk
            for line in text.splitlines():
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        d = json.loads(raw)
                        if current_event == "delta":
                            full_content += d.get("text", "")
                        elif current_event == "mode":
                            final_mode = d.get("mode")
                    except Exception:  # noqa: BLE001
                        pass
            yield chunk

        # Persist assistant reply using own session (request session already closed)
        import sqlalchemy

        from app.core.database import SessionLocal
        save_db = SessionLocal()
        try:
            asst = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=full_content,
                sources=json.dumps(sources, ensure_ascii=False) if sources else None,
                mode=final_mode,
            )
            save_db.add(asst)
            save_db.execute(
                sqlalchemy.text("UPDATE chat_sessions SET updated_at = NOW() WHERE id = :sid"),
                {"sid": session_id},
            )
            save_db.commit()
        except Exception:  # noqa: BLE001
            save_db.rollback()
        finally:
            save_db.close()

    return StreamingResponse(
        stream_and_save(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
