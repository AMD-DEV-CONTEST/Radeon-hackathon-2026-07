"""Tests for the external tools layer (protocol / intent / providers / registry).

Design guarantees under test:
- Unified envelope always carries source_confidence + relevance_score + TTL.
- Mock data is deterministic (same symbol+days → identical series), zero network.
- Intent routing separates compute from query (the core review fix).
- Real mode degrades gracefully when akshare is unavailable (mock_fallback).
- The query chain returns an auditable `steps` trace for Dify rendering.

Run:  cd track2-agentic-ai && pytest tests/test_external_tools.py -v
"""

from __future__ import annotations

import os

os.environ["EXTERNAL_TOOLS_MODE"] = "mock"  # tests must never hit the network

from src.tools.external.protocol import ToolResult, SOURCE_CONFIDENCE, now_iso, ttl_iso
from src.tools.external.intent import (
    classify_intent, STRATEGY_GENERATION, LOCAL_COMPUTE, INFO_QUERY, GENERAL,
)
from src.tools.external.providers import market_data, announcement, search
from src.tools.external.registry import handle_query
from src.tools.external.knowledge_store import CandidateKnowledgeStore, PROMOTE_THRESHOLD


# ── Protocol ─────────────────────────────────────────────────────────


def test_protocol_envelope_fields():
    r = ToolResult(
        success=True, tool="market_data", source="mock",
        source_confidence=0.4, relevance_score=0.9,
        data_mode="mock", data={"x": 1}, limitations=["合成数据"],
    )
    d = r.to_dict()
    for key in ("success", "source", "source_confidence", "relevance_score",
                "retrieved_at", "effective_until", "data_mode", "data",
                "limitations", "steps"):
        assert key in d, f"missing {key}"
    assert d["retrieved_at"].endswith("+08:00")


def test_protocol_source_confidence_tiers():
    assert SOURCE_CONFIDENCE["official"] == 0.9
    assert SOURCE_CONFIDENCE["aggregator"] == 0.6
    assert SOURCE_CONFIDENCE["mock"] == 0.4


def test_ttl_ordering():
    assert ttl_iso(5) > now_iso()


# ── Intent classification ────────────────────────────────────────────


def test_intent_strategy_generation():
    for q in ("帮我写一个双均线策略", "回测 MA20/MA60", "设计一个布林带突破策略"):
        assert classify_intent(q).intent == STRATEGY_GENERATION, q


def test_intent_local_compute():
    # Computation must NEVER be routed to RAG/external
    for q in ("计算组合的 VaR", "算一下最大回撤", "夏普比率是多少",
              "做因子 IC 检验", "用 Black-Scholes 给期权定价", "有效前沿怎么算"):
        assert classify_intent(q).intent == LOCAL_COMPUTE, q


def test_intent_info_query():
    for q in ("510300 最新行情", "查一下茅台股价", "有什么公告", "美联储最新利率政策"):
        assert classify_intent(q).intent == INFO_QUERY, q


def test_intent_general():
    assert classify_intent("你好").intent == GENERAL
    assert classify_intent("今天天气怎么样").intent == GENERAL


def test_intent_precedence_strategy_over_compute():
    # "回测" (strategy) must win over "回撤" (compute)
    assert classify_intent("回测一下双均线策略的最大回撤").intent == STRATEGY_GENERATION


# ── Providers (mock determinism + graceful degradation) ──────────────


def test_market_data_deterministic():
    a = market_data("510300.SH", days=10).to_dict()
    b = market_data("510300.SH", days=10).to_dict()
    assert a["data"]["rows"] == b["data"]["rows"], "mock 数据必须确定性可复现"
    assert len(a["data"]["rows"]) == 10
    assert a["data_mode"] == "mock"
    assert a["source_confidence"] == 0.4
    assert any("合成" in lim for lim in a["limitations"]), "必须明确标注合成数据"


def test_market_data_ttl_present():
    a = market_data().to_dict()
    assert a["effective_until"] > a["retrieved_at"]


def test_announcement_mock_structure():
    a = announcement("510300.SH").to_dict()
    assert a["success"] is True
    assert isinstance(a["data"]["rows"], list) and len(a["data"]["rows"]) >= 3
    assert "title" in a["data"]["rows"][0]


def test_real_mode_degrades_without_akshare():
    # akshare is not installed in CI → real must degrade, not crash
    r = market_data("510300.SH", days=5, mode="real")
    assert r.success is True  # falls back to mock
    assert r.data_mode in ("mock_fallback", "mock")


# ── Query chain (auditable steps + fallback) ─────────────────────────


def test_query_chain_steps_present():
    result = handle_query("510300 最新行情怎么样").to_dict()
    assert result["success"] is True
    assert len(result["steps"]) >= 2
    step_names = [s["step"] for s in result["steps"]]
    assert "intent" in step_names
    assert "fallback_external" in step_names, "行情类问题必须走外部降级"


def test_query_market_fallback_uses_mock():
    result = handle_query("510300 最新行情怎么样").to_dict()
    tool = result["data"]["results"][0]
    assert tool["tool"] == "market_data"
    assert tool["data_mode"] in ("mock", "mock_fallback")


def test_query_announcement_fallback():
    result = handle_query("510300 最近有什么公告").to_dict()
    tools = [r["tool"] for r in result["data"]["results"]]
    assert "announcement" in tools


def test_query_strategy_routes_to_dsl():
    result = handle_query("帮我写一个双均线策略").to_dict()
    assert result["route"] == "dsl_pipeline"


def test_query_compute_stays_local():
    result = handle_query("计算组合的 VaR 和 CVaR").to_dict()
    assert result["route"] == "local_compute"
    assert "fallback_external" not in [s["step"] for s in result["steps"]], "计算类禁止联网"


def test_query_rag_hit_for_rules():
    result = handle_query("A股交易的 T+1 规则是什么").to_dict()
    assert result["route"] == "rag"


# ── Search provider (module B) ───────────────────────────────────────


def test_search_mock_deterministic():
    a = search("美联储最新政策").to_dict()
    b = search("美联储最新政策").to_dict()
    assert a["data"]["rows"] == b["data"]["rows"]
    assert len(a["data"]["rows"]) >= 3
    assert a["data_mode"] == "mock"
    assert any("合成" in lim for lim in a["limitations"])


def test_search_real_degrades_without_key():
    # No TAVILY_API_KEY in CI → real must degrade to mock, not crash
    r = search("美联储", mode="real")
    assert r.success is True
    assert r.data_mode in ("mock_fallback", "mock")


def test_query_search_fallback_for_news_analysis():
    # Q24-style: news/macro analysis → search tool
    result = handle_query("美联储议息声明，鹰派鸽派情绪分析").to_dict()
    assert result["route"] == "external_fallback"
    tools = [r["tool"] for r in result["data"]["results"]]
    assert "search" in tools


def test_query_announcement_search_combined():
    # Q25-style: 财报(announcement) + 电话会分析(search)
    result = handle_query("分析财报电话会议文本的语气变化").to_dict()
    tools = [r["tool"] for r in result["data"]["results"]]
    assert "search" in tools or "announcement" in tools


# ── Candidate knowledge store (module C) ─────────────────────────────


def test_candidate_store_ttl_roundtrip():
    c = CandidateKnowledgeStore()
    r = market_data("510300.SH", days=3)
    c.add("market_data:510300.SH", r)
    item = c.get("market_data:510300.SH")
    assert item is not None and item.tool == "market_data"
    assert c.cleanup() == 0  # not expired yet


def test_candidate_store_expiry():
    c = CandidateKnowledgeStore()
    # Expired TTL (retrieved 1h ago, effective 5min after)
    expired = ToolResult(
        success=True, tool="market_data", source="x",
        source_confidence=0.4, relevance_score=0.5,
        retrieved_at="2026-01-01T00:00:00+08:00",
        effective_until="2026-01-01T00:05:00+08:00",
        data_mode="mock", data={},
    )
    c.add("stale", expired)
    assert c.get("stale") is None
    assert c.cleanup() == 1


def test_candidate_not_promoted_for_mock():
    # Mock (0.4) must NEVER auto-promote into semantic memory
    from src.agent.memory import AgentMemory
    c = CandidateKnowledgeStore()
    mem = AgentMemory()
    c.add("market_data:510300.SH", market_data("510300.SH", days=3))
    assert c.promote("market_data:510300.SH", mem) is False
    assert mem.semantic.experience_rules == []


def test_candidate_promote_confirmed_works():
    from src.agent.memory import AgentMemory
    c = CandidateKnowledgeStore()
    mem = AgentMemory()
    c.add("search:测试", search("测试查询"))
    # Explicit user confirmation ("记住这条") bypasses confidence gate
    assert c.promote_confirmed("search:测试", mem, label="用户确认保留") is True
    assert len(mem.semantic.experience_rules) == 1


def test_candidate_auto_promote_high_confidence():
    from src.agent.memory import AgentMemory
    c = CandidateKnowledgeStore()
    mem = AgentMemory()
    official = ToolResult(
        success=True, tool="market_data", source="SSE Official",
        source_confidence=SOURCE_CONFIDENCE["official"],  # 0.9
        relevance_score=0.95, data_mode="public_snapshot",
        data={"rows": []}, effective_until=ttl_iso(10),
    )
    c.add("official:sse", official)
    assert c.promote("official:sse", mem) is True
    assert len(mem.semantic.experience_rules) == 1
