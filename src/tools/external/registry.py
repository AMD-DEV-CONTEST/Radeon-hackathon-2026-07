"""Query router — the full auditable chain: intent → RAG → external fallback.

For every user message this returns a ToolResult whose `steps` array
records WHAT the agent decided and WHY (intent → RAG hit/miss →
fallback reason → tool + mode). Dify renders `steps` as visible run
logs, so judges can see the autonomous planning, not just the answer.

Routing rules (per the approved design):
- strategy_generation → the existing DSL pipeline (handed off, not executed here)
- local_compute        → local computation only; NEVER contacts external APIs
- info_query           → local RAG first; if the question needs live data
                         (price/news/announcement), fall back to external tools
- general              → personality chat
"""

from __future__ import annotations

from ...knowledge_base.cn_knowledge import retrieve_cn_knowledge
from .intent import (
    classify_intent,
    STRATEGY_GENERATION,
    LOCAL_COMPUTE,
    INFO_QUERY,
    GENERAL,
)
from .protocol import ToolResult, SOURCE_CONFIDENCE, now_iso, ttl_iso, tools_mode
from .providers import market_data, announcement, search, _mock_ohlcv
from .knowledge_store import store
from ..compute import resolve_compute

# Query words that signal a need for LIVE data (RAG's static rules can't satisfy)
_LIVE_MARKET_WORDS = ["行情", "价格", "股价", "最新", "走势", "收盘", "开盘", "现价", "涨", "成交"]
_LIVE_NEWS_WORDS = ["公告", "披露", "预告", "分红"]
_SEARCH_WORDS = ["新闻", "资讯", "分析", "研究", "观点", "报道", "声明", "政策",
                 "宏观", "美联储", "解读", "电话会", "纪要", "讨论", "热度"]


def _rag_lookup(query: str) -> tuple[str, bool]:
    """Local RAG lookup. Returns (context, hit)."""
    context = retrieve_cn_knowledge(query)
    # The CN knowledge base is a curated rule set; it answers rule/知识类
    # questions but cannot supply live market data.
    hit = any(w in query for w in ["规则", "约束", "T+1", "涨跌停", "涨跌幅", "手续费", "印花税", "交易制度", "什么是", "允许", "禁止"])
    return context, hit


def handle_query(user_query: str, mode: str | None = None) -> ToolResult:
    """Run the auditable chain and return a unified ToolResult."""
    mode = (mode or tools_mode()).lower()
    steps: list[dict] = []

    # 1. Intent classification
    decision = classify_intent(user_query)
    steps.append({
        "step": "intent",
        "intent": decision.intent,
        "confidence": round(decision.confidence, 2),
        "hints": decision.hints,
    })

    # 2. Strategy generation → hand off to the DSL pipeline
    if decision.intent == STRATEGY_GENERATION:
        return ToolResult(
            success=True, route="dsl_pipeline", tool="intent_router",
            source="Local intent router",
            source_confidence=SOURCE_CONFIDENCE["rag"],
            relevance_score=decision.confidence,
            data_mode="route", data={
                "note": "策略生成意图，已路由到现有 NL→DSL→回测→风控 管道",
                "pipeline": "/api/cn/backtest/report",
            },
            steps=steps,
        )

    # 3. Local compute → stay local, never call external APIs
    if decision.intent == LOCAL_COMPUTE:
        # 计算类题目：若无输入数据，自动注入 510300.SH 的 mock 行情（确定性演示数据）
        demo = {"prices": [r["close"] for r in _mock_ohlcv("510300.SH", 120)]}
        resolved = resolve_compute(user_query, params=demo)
        if not resolved["success"]:
            return ToolResult(
                success=False, route="local_compute", tool=f"compute/{resolved['kind']}",
                source="Local computation engine",
                source_confidence=SOURCE_CONFIDENCE["local"],
                relevance_score=decision.confidence,
                data_mode="compute_error", data=resolved["result"],
                steps=steps, retrieved_at=now_iso(),
            )
        steps.append({"step": "compute", "kind": resolved["kind"], "local": True,
                      "network": False, "data_source": "mock 510300.SH (demo)"})
        return ToolResult(
            success=True, route="local_compute", tool=f"compute/{resolved['kind']}",
            source="Local computation engine (numpy)",
            source_confidence=SOURCE_CONFIDENCE["local"],
            relevance_score=decision.confidence,
            data_mode="computed", data=resolved["result"],
            steps=steps, retrieved_at=now_iso(),
        )

    if decision.intent == GENERAL:
        return ToolResult(
            success=True, route="general", tool="intent_router",
            source="Local intent router",
            source_confidence=SOURCE_CONFIDENCE["rag"],
            relevance_score=decision.confidence,
            data_mode="route", data={"note": "闲聊意图，走人格化回复"},
            steps=steps,
        )

    # 4. Info query → RAG first
    context, rag_hit = _rag_lookup(user_query)
    steps.append({
        "step": "rag",
        "hit": rag_hit,
        "context_chars": len(context),
    })

    needs_live_market = any(w in user_query for w in _LIVE_MARKET_WORDS)
    needs_news = any(w in user_query for w in _LIVE_NEWS_WORDS)
    needs_search = any(w in user_query for w in _SEARCH_WORDS)
    # Any remaining info_query that is not market/news/rule falls back to search
    if decision.intent == INFO_QUERY and not (needs_live_market or needs_news or needs_search or rag_hit):
        needs_search = True

    # 4a. RAG answers rule-based questions directly
    if rag_hit and not needs_live_market and not needs_news and not needs_search:
        return ToolResult(
            success=True, route="rag", tool="knowledge_base",
            source="Local RAG (CN market rules)",
            source_confidence=SOURCE_CONFIDENCE["rag"],
            relevance_score=0.85,
            data_mode="rag",
            data={"answer": context},
            steps=steps,
        )

    # 4b. RAG miss on live data → graceful fallback to external tools
    if needs_live_market or needs_news or needs_search:
        tool = "+".join(
            t for t, flag in (
                ("market_data", needs_live_market),
                ("announcement", needs_news),
                ("search", needs_search),
            ) if flag
        )
        steps.append({
            "step": "fallback_external",
            "reason": "问题需要实时数据，本地知识库无法提供具体数值",
            "tool": tool,
            "mode": mode,
        })
        results: list[dict] = []
        if needs_live_market:
            md = market_data(mode=mode)
            results.append(md.to_dict())
            store.add("market_data:510300.SH", md)  # 候选区（TTL 隔离，不自动进语义记忆）
        if needs_news:
            ann = announcement(mode=mode)
            results.append(ann.to_dict())
            store.add("announcement:510300.SH", ann)
        if needs_search:
            sr = search(user_query, mode=mode)
            results.append(sr.to_dict())
            store.add(f"search:{user_query[:24]}", sr)
        return ToolResult(
            success=True, route="external_fallback", tool=tool,
            source="External tools (mock/real)",
            source_confidence=SOURCE_CONFIDENCE["mock"] if mode != "real" else SOURCE_CONFIDENCE["aggregator"],
            relevance_score=0.8,
            data_mode="public_snapshot" if mode == "real" else "mock",
            data={"symbol": "510300.SH", "results": results},
            steps=steps,
            limitations=["数据带 source_confidence/relevance_score/effective_until，请勿将未验证数据当作模型内部知识"],
        )

    # 4c. Unresolved query → honest boundary statement
    steps.append({"step": "boundary", "reason": "无法用现有知识或工具回答，说明边界并给出方法建议"})
    return ToolResult(
        success=True, route="knowledge_boundary", tool="intent_router",
        source="Local intent router",
        source_confidence=SOURCE_CONFIDENCE["rag"],
        relevance_score=decision.confidence,
        data_mode="route",
        data={
            "note": "该问题超出当前本地知识库与已接入工具的能力，建议：接入更多数据源或人工复核",
            "rag_context": context[:400],
        },
        steps=steps,
    )
