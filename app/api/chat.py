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
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.dependencies import get_db, require_member
from app.core.utils import ok, real_client_ip
from app.models.chat_log import ChatLog
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
    filters = {
        "brand": (body.filters or {}).get("brand"),
        "category": (body.filters or {}).get("category"),
    }
    try:
        chunks = await run_in_threadpool(
            chat_service.retrieve, body.message, settings.RAG_TOP_K, filters
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="知识库暂不可用，请稍后再试") from exc
    sources = chat_service.sources_from(chunks)

    # 3. 记一条 chat_log（计入当日配额；token 用量在流结束后回填）
    history = [t.model_dump() for t in (body.history or [])]
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
        chat_service.stream_answer(body.message, history, chunks, sources, log.id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
