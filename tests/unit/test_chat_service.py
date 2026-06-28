"""Unit tests for the RAG chat service.

These cover the pure prompt/source-building logic — no external packages
(`openai` / `pymilvus`) are imported, since those deps are loaded lazily.
"""
from app.services import chat_service


def _chunk(name, page, text, brand="siemens", category="plc-manual", score=0.9):
    return {
        "score": score,
        "text": text,
        "metadata": {
            "document_name": name,
            "page": page,
            "brand": brand,
            "category": category,
        },
    }


def test_sources_dedupe_by_doc_and_page():
    chunks = [
        _chunk("A.pdf", 1, "x"),
        _chunk("A.pdf", 1, "y"),  # duplicate doc+page -> dropped
        _chunk("A.pdf", 2, "z"),
        _chunk("B.pdf", 1, "w"),
    ]
    sources = chat_service.sources_from(chunks)
    assert len(sources) == 3
    assert {(s["document_name"], s["page"]) for s in sources} == {
        ("A.pdf", 1), ("A.pdf", 2), ("B.pdf", 1),
    }
    assert sources[0]["brand"] == "siemens"


def test_build_messages_grounded_structure():
    chunks = [_chunk("S7 手册.pdf", 12, "Modbus TCP 配置步骤……")]
    msgs = chat_service.build_messages("怎么配 Modbus TCP?", None, chunks)
    assert msgs[0]["role"] == "system"
    assert "只能依据" in msgs[0]["content"]
    assert msgs[-1]["role"] == "user"
    # 用户问题、来源标注与原文都在最后一轮
    assert "怎么配 Modbus TCP?" in msgs[-1]["content"]
    assert "《S7 手册.pdf》p.12" in msgs[-1]["content"]
    assert "Modbus TCP 配置步骤" in msgs[-1]["content"]


def test_build_messages_trims_history():
    chunks = [_chunk("A.pdf", 1, "x")]
    history = [{"role": "user", "content": f"q{i}"} for i in range(10)]
    msgs = chat_service.build_messages("最新问题", history, chunks)
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["content"].endswith("最新问题")
    history_msgs = msgs[1:-1]
    assert len(history_msgs) <= 6  # _MAX_HISTORY


def test_build_messages_skips_bad_history_roles():
    chunks = [_chunk("A.pdf", 1, "x")]
    history = [
        {"role": "system", "content": "ignore me"},
        {"role": "user", "content": ""},  # empty -> skipped
        {"role": "assistant", "content": "上文回答"},
    ]
    msgs = chat_service.build_messages("再问", history, chunks)
    roles = [m["role"] for m in msgs]
    assert roles[0] == "system"
    # 只有合法的 assistant 历史被保留（system/空 user 被过滤）
    assert msgs[1] == {"role": "assistant", "content": "上文回答"}
    assert roles[-1] == "user"


def test_build_messages_empty_context():
    msgs = chat_service.build_messages("无关问题", None, [])
    assert "（无相关片段）" in msgs[-1]["content"]


def test_determine_mode_no_chunks_returns_fallback():
    assert chat_service.determine_mode([]) == "fallback"


def test_determine_mode_low_score_returns_fallback():
    # 命中但分数都偏低（<0.7 阈值）—— 视为弱相关，切到 fallback
    chunks = [_chunk("A.pdf", 1, "x", score=0.3), _chunk("A.pdf", 2, "y", score=0.65)]
    assert chat_service.determine_mode(chunks) == "fallback"


def test_determine_mode_high_score_returns_grounded():
    chunks = [_chunk("A.pdf", 1, "x", score=0.75), _chunk("A.pdf", 2, "y", score=0.4)]
    # 只要有一个 ≥ 阈值就 grounded
    assert chat_service.determine_mode(chunks) == "grounded"


def test_build_messages_fallback_mode_omits_context():
    chunks = [_chunk("A.pdf", 1, "irrelevant text")]
    msgs = chat_service.build_messages("fx 5u 是什么？", None, chunks, mode="fallback")
    # fallback 用专用 system prompt，user turn 不带【知识库片段】
    assert "通用工业自动化知识" in msgs[0]["content"]
    assert "知识库片段" not in msgs[-1]["content"]
    assert msgs[-1]["content"] == "fx 5u 是什么？"


def test_build_messages_grounded_mode_keeps_context():
    chunks = [_chunk("S7 手册.pdf", 12, "Modbus TCP 配置步骤……")]
    msgs = chat_service.build_messages("怎么配 Modbus TCP?", None, chunks, mode="grounded")
    assert "只能依据" in msgs[0]["content"]
    assert "知识库片段" in msgs[-1]["content"]
