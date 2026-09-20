"""Tests for explicit preference / rule extraction into semantic memory.

Covers the memory-consistency scenarios S3 (cross-session retrieval) and
S8 (rule cancellation), plus false-positive guardrails.

Run:  cd track2-agentic-ai && pytest tests/test_memory_extract.py -v
"""

from __future__ import annotations

import tempfile

from src.agent.memory_extract import (
    extract_preferences,
    extract_cancellations,
    apply_memory_updates,
)
from src.agent.memory import AgentMemory


# ── Extraction ───────────────────────────────────────────────────────


def test_extract_risk_preferences_s3():
    found = extract_preferences("记住：我的风险偏好是保守型，最大单日回撤容忍 2%。")
    assert found == {"risk_tolerance": "conservative", "max_daily_drawdown": "2%"}


def test_extract_stop_loss_s8():
    found = extract_preferences("记住：我的止损线统一设在 -8%。")
    assert found == {"unified_stop_loss": "-8%"}


def test_extract_risk_mapping_variants():
    assert extract_preferences("我的风险偏好是激进型")["risk_tolerance"] == "aggressive"
    assert extract_preferences("风险偏好：稳健")["risk_tolerance"] == "moderate"
    assert extract_preferences("我是中等风险偏好")["risk_tolerance"] == "moderate"


def test_no_extract_on_queries():
    # Query-style messages must NOT create/overwrite long-term rules
    assert extract_preferences("我现在整体的止损规则是什么？") == {}
    assert extract_preferences("我之前跟你说过我的风险偏好，还记得吗？") == {}
    assert extract_preferences("帮我评估一下全仓 BTC 这个策略能不能跑") == {}
    assert extract_preferences("茅台跌破 1700 了，帮我看要不要止损") == {}


def test_no_extract_on_opinions():
    # A user opinion ("I think ...") is not a preference rule
    assert extract_preferences("我认为茅台明年能到 2500，这是我的个人判断。") == {}
    assert extract_preferences("我觉得 BTC 要涨") == {}


def test_no_extract_on_position_state():
    # Session state (positions) stays in working memory, not semantic
    assert extract_preferences("我目前仓位：50% A股、30% 美股、20% 现金。") == {}
    assert extract_preferences("我清仓了 A 股。现在改成 20% 美股、80% 现金。") == {}


# ── Cancellation ─────────────────────────────────────────────────────


def test_cancel_stop_loss_s8():
    removed = extract_cancellations(
        "取消这条规则，以后止损都按各策略自带参数执行，不用统一止损。"
    )
    assert "unified_stop_loss" in removed


def test_cancel_other_rules():
    assert "max_daily_drawdown" in extract_cancellations("撤销回撤容忍的限制")
    assert "risk_tolerance" in extract_cancellations("取消之前的风险偏好设置")


# ── Cross-session persistence (S3) ───────────────────────────────────


def test_cross_session_retrieval_s3():
    with tempfile.TemporaryDirectory() as tmp:
        # Session A: user states long-term preferences
        mem_a = AgentMemory(data_dir=tmp, session_id="sessA")
        applied = apply_memory_updates(mem_a, "记住：我的风险偏好是保守型，最大单日回撤容忍 2%。")
        assert applied["stored"]["risk_tolerance"] == "conservative"
        mem_a.consolidate()

        # Session B: fresh memory facade, same data dir (simulated new chat)
        mem_b = AgentMemory(data_dir=tmp, session_id="sessB")
        prompt_ctx = mem_b.format_semantic_for_prompt()
        assert "Risk tolerance: conservative" in prompt_ctx
        assert "Max daily drawdown tolerance: 2%" in prompt_ctx


# ── Cancellation persists (S8) ───────────────────────────────────────


def test_cancellation_persists_s8():
    with tempfile.TemporaryDirectory() as tmp:
        mem_a = AgentMemory(data_dir=tmp, session_id="sessA")
        apply_memory_updates(mem_a, "记住：我的止损线统一设在 -8%。")
        mem_a.consolidate()

        # User cancels the rule
        mem_a2 = AgentMemory(data_dir=tmp, session_id="sessA2")
        applied = apply_memory_updates(mem_a2, "取消这条规则，以后止损都按各策略自带参数执行，不用统一止损。")
        assert applied["removed"] == ["unified_stop_loss"]

        # New session: the cancelled rule must be gone
        mem_b = AgentMemory(data_dir=tmp, session_id="sessB")
        prompt_ctx = mem_b.format_semantic_for_prompt()
        assert "Unified stop-loss" not in prompt_ctx
        assert "-8%" not in prompt_ctx


# ── apply_memory_updates returns accurate summary ────────────────────


def test_apply_summary_shape():
    with tempfile.TemporaryDirectory() as tmp:
        mem = AgentMemory(data_dir=tmp)
        summary = apply_memory_updates(mem, "普通消息，没有偏好")
        assert summary == {"stored": {}, "removed": []}
