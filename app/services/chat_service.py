"""Smart-consultation (RAG chat) service. §4.3.12

Retrieve top-k chunks from Milvus (BGE-M3, CPU) -> build a grounded prompt ->
stream the answer from an OpenAI-compatible LLM (DeepSeek by default).

Heavy deps (`openai`) are imported lazily so importing this module stays cheap
and unit tests for prompt/source building need no external packages. Retrieval
reuses ``milvus_service`` (which also lazy-loads pymilvus / sentence-transformers).
"""
from __future__ import annotations

import json
from typing import Any

from app.core.config import settings
from app.services.milvus_service import milvus_service

# 最多带入的历史轮数（user/assistant 合计），防止 prompt 过长
_MAX_HISTORY = 6

_SYSTEM_PROMPT = (
    "你是 openIndu 工业自动化知识库助手。"
    "只能依据下面提供的【知识库片段】回答用户问题；"
    "若片段不足以回答，明确告知『未在知识库中找到相关资料，建议到下载中心查阅原始手册或换个问法』，"
    "严禁编造型号参数、接线、寄存器地址、版本号等任何未在片段中出现的内容。"
    "用中文作答，涉及参数或操作步骤时注明出自哪篇文档。"
)

_LLM_CLIENT = None


def _get_client():
    """Lazily build the async OpenAI-compatible client (DeepSeek by default)."""
    global _LLM_CLIENT
    if _LLM_CLIENT is None:
        from openai import AsyncOpenAI

        _LLM_CLIENT = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
    return _LLM_CLIENT


def retrieve(message: str, top_k: int | None = None, filters: dict | None = None) -> list[dict]:
    """Vector search over the knowledge base. Blocking — call via run_in_threadpool."""
    where = {k: v for k, v in (filters or {}).items() if v}
    return milvus_service.search(
        message, top_k=top_k or settings.RAG_TOP_K, where_filter=where or None
    )


def sources_from(chunks: list[dict]) -> list[dict]:
    """Dedupe retrieved chunks into citation entries (by document_name + page)."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for c in chunks:
        meta = c.get("metadata", {})
        key = (meta.get("document_name", ""), meta.get("page", 0))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "document_name": meta.get("document_name", ""),
            "page": meta.get("page", 0),
            "brand": meta.get("brand", ""),
            "category": meta.get("category", ""),
            "score": c.get("score", 0),
        })
    return out


def build_messages(message: str, history: list[dict] | None, chunks: list[dict]) -> list[dict]:
    """Assemble chat messages: system + (trimmed) history + grounded user turn.

    The user question is embedded as data inside the final user turn (after the
    retrieved context) and never overrides the system instruction — basic
    prompt-injection hardening.
    """
    context_lines = []
    for i, c in enumerate(chunks, 1):
        meta = c.get("metadata", {})
        name = meta.get("document_name", "未知文档")
        page = meta.get("page", 0)
        context_lines.append(f"[来源{i}]《{name}》p.{page}\n{c.get('text', '')}")
    context = "\n\n".join(context_lines) if context_lines else "（无相关片段）"

    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for turn in (history or [])[-_MAX_HISTORY:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({
        "role": "user",
        "content": f"【知识库片段】\n{context}\n\n【用户问题】\n{message}",
    })
    return messages


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_answer(message, history, chunks, sources, log_id):
    """Async generator yielding SSE frames: sources -> delta* -> done (or error).

    On completion it backfills the chat_logs row (log_id) with token usage using
    a fresh DB session — the request-scoped session is already closed by the time
    a StreamingResponse body runs.
    """
    # 1) 来源先行，前端可立即展示"正在依据 N 篇资料作答"
    yield _sse("sources", sources)

    if not settings.LLM_API_KEY:
        yield _sse("error", {"detail": "智能咨询未配置大模型（缺少 LLM_API_KEY）"})
        return

    usage: dict = {}
    try:
        client = _get_client()
        stream = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=build_messages(message, history, chunks),
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                }
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield _sse("delta", {"text": delta.content})
    except Exception as exc:  # noqa: BLE001 - surface a clean SSE error to the client
        yield _sse("error", {"detail": f"生成失败：{exc}"})
        return

    _record_usage(log_id, usage)
    yield _sse("done", {"finish_reason": "stop", "usage": usage})


def _record_usage(log_id: int | None, usage: dict) -> None:
    """Backfill token usage onto the chat_logs row (best-effort, own session)."""
    if not log_id or not usage:
        return
    from app.core.database import SessionLocal
    from app.models.chat_log import ChatLog

    db = SessionLocal()
    try:
        row = db.query(ChatLog).filter(ChatLog.id == log_id).first()
        if row:
            row.prompt_tokens = usage.get("prompt_tokens")
            row.completion_tokens = usage.get("completion_tokens")
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
