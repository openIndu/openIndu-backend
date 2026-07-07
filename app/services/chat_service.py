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

# 严格 grounded 模式：只能依据知识库片段回答（默认模式，工业参数零容错）。
_GROUNDED_SYSTEM_PROMPT = (
    "你是 openIndu 工业自动化知识库助手。"
    "只能依据下面提供的【知识库片段】回答用户问题；"
    "若片段不足以回答，明确告知『未在知识库中找到相关资料，建议到下载中心查阅原始手册或换个问法』，"
    "严禁编造型号参数、接线、寄存器地址、版本号等任何未在片段中出现的内容。"
    "用中文作答，涉及参数或操作步骤时注明出自哪篇文档。"
)

# Fallback 模式：知识库无命中时启用，允许 LLM 用通用工业知识回答；
# 前端会单独显示『非来自本平台知识库』警告条，因此 system prompt 不需要重复警告——
# 但仍然严禁编造具体型号的参数细节（用户应以厂家原版手册为准）。
_FALLBACK_SYSTEM_PROMPT = (
    "你是 openIndu 工业自动化助手。"
    "当前用户的问题在本平台知识库中没有相关资料，请基于你掌握的通用工业自动化知识作答。"
    "对于具体型号的寄存器地址、接线图、电气参数、版本号等关键细节，"
    "如不能 100% 确定，必须明示『请以厂家原版手册为准』，不得编造数字。"
    "回答开头无需提示来源缺失（前端会自行标注），直接进入正文。用中文作答。"
)

# Grounded → Fallback 的切换门槛（基于 COSINE 相似度，[0,1]）。
# 经验值：强相关问题 top-1 score ≥ 0.7；< 0.7 多为弱相关（同领域不同代号/异品牌词面命中等）
# —— 这类情况下让 LLM 用通用知识回答比硬咬不匹配的片段体验更好。
# 业务案例：
#   富士以太网通信 (top=0.74) → grounded ✅
#   富士 PLC 编程示例 (top=0.67) → fallback（命中触摸屏/异品牌运控，不算真相关）
#   FX5U 地址规划 (top=0.54) → fallback ✅
_FALLBACK_SCORE_THRESHOLD = 0.7

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


def determine_mode(chunks: list[dict]) -> str:
    """判定回答模式：grounded（依据知识库）/ fallback（依据 LLM 通用知识）。

    切换条件：chunks 为空，或最高 score 低于阈值——说明检索结果与问题弱相关。
    """
    if not chunks:
        return "fallback"
    top_score = max((c.get("score", 0) for c in chunks), default=0)
    if top_score < _FALLBACK_SCORE_THRESHOLD:
        return "fallback"
    return "grounded"


def _enrich_query(message: str, history: list[dict] | None) -> str:
    """Manual fallback: prepend recent conversation context to the search query
    so the vector embedding carries brand / series / topic continuity."""
    if not history:
        return message
    parts: list[str] = []
    for turn in history[-3:]:
        content = (turn.get("content") or "").strip()
        if content:
            parts.append(content[:200])
    if parts:
        return " ".join(parts) + " " + message
    return message


async def rewrite_query(message: str, history: list[dict] | None) -> str:
    """Use the LLM to rewrite a multi-turn follow-up into a self-contained
    search query (e.g. "数据寄存器地址呢？" + history → "三菱 FX3U 数据寄存器
    地址分配") so the BGE-M3 embedding stays on-topic.

    Falls back to ``_enrich_query`` when the LLM is unavailable or the rewrite
    returns empty text. The call is cheap: max 100 output tokens with
    temperature 0 (< 0.5 s).
    """
    if not history or not settings.LLM_API_KEY:
        return _enrich_query(message, history)

    # Build a compact history summary (last 4 turns, 200 chars each)
    lines: list[str] = []
    for turn in history[-4:]:
        role = turn.get("role", "")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            label = "用户" if role == "user" else "助手"
            lines.append(f"{label}: {content[:200]}")
    if not lines:
        return message

    rewrite_prompt = (
        "你是搜索查询改写助手。根据对话历史和用户最新消息，"
        "生成一个自包含的搜索查询（中文），包含品牌、型号、主题等关键信息。"
        "只输出查询文本，不要任何解释。\n\n"
        f"对话历史:\n{chr(10).join(lines)}\n\n"
        f"用户最新消息: {message}\n\n"
        "改写后的查询:"
    )

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": rewrite_prompt}],
            temperature=0,
            max_tokens=100,
        )
        rewritten = response.choices[0].message.content
        if rewritten and rewritten.strip():
            return rewritten.strip()
    except Exception:
        pass  # LLM unavailable → fall through to manual enrichment

    return _enrich_query(message, history)


def retrieve(
    message: str,
    top_k: int | None = None,
    filters: dict | None = None,
) -> list[dict]:
    """Vector search over the knowledge base. Blocking — call via run_in_threadpool.

    The caller should first pass the user message through ``rewrite_query()``
    (with conversation history) to produce a self-contained search query;
    then call this function with the rewritten query.
    """
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


def build_messages(
    message: str,
    history: list[dict] | None,
    chunks: list[dict],
    mode: str = "grounded",
) -> list[dict]:
    """Assemble chat messages: system + (trimmed) history + user turn.

    - mode="grounded": 严格基于检索片段作答，user turn 内嵌【知识库片段】。
    - mode="fallback": 通用工业知识作答，user turn 不带知识库上下文。

    无论哪种模式，用户问题都嵌在 user role 的内容里、不能覆盖 system 指令——
    这是基本的 prompt-injection 防护。
    """
    if mode == "fallback":
        messages: list[dict] = [{"role": "system", "content": _FALLBACK_SYSTEM_PROMPT}]
        for turn in (history or [])[-_MAX_HISTORY:]:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})
        return messages

    # grounded
    context_lines = []
    for i, c in enumerate(chunks, 1):
        meta = c.get("metadata", {})
        name = meta.get("document_name", "未知文档")
        page = meta.get("page", 0)
        context_lines.append(f"[来源{i}]《{name}》p.{page}\n{c.get('text', '')}")
    context = "\n\n".join(context_lines) if context_lines else "（无相关片段）"

    messages = [{"role": "system", "content": _GROUNDED_SYSTEM_PROMPT}]
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
    """Async generator yielding SSE frames: sources -> mode -> delta* -> done (or error).

    根据 determine_mode 决定是 grounded 还是 fallback：
    - grounded: sources 内含命中文档；LLM 严格依据片段作答。
    - fallback: sources 为空；前端据 mode 事件展示『非知识库』警告条。

    On completion it backfills the chat_logs row (log_id) with token usage using
    a fresh DB session — the request-scoped session is already closed by the time
    a StreamingResponse body runs.
    """
    mode = determine_mode(chunks)
    # 1) sources：fallback 模式下用空数组（保持事件协议向后兼容）
    yield _sse("sources", sources if mode == "grounded" else [])
    # 2) mode：明示当前回答来源，前端据此切换 UI 样式
    yield _sse("mode", {"mode": mode})

    if not settings.LLM_API_KEY:
        yield _sse("error", {"detail": "智能咨询未配置大模型（缺少 LLM_API_KEY）"})
        return

    usage: dict = {}
    try:
        client = _get_client()
        stream = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=build_messages(message, history, chunks, mode=mode),
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
    yield _sse("done", {"finish_reason": "stop", "usage": usage, "mode": mode})


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
