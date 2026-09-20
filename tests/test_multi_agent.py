"""Tests for the multi-agent system: protocol, retrieval, reasoning, risk, orchestrator."""

from __future__ import annotations

import json

import pytest

from src.agent.protocol import AgentMessage
from src.agent.retrieval_agent import run_retrieval_agent
from src.agent.reasoning_agent import run_reasoning_agent, _neutral_intent, _extract_json
from src.agent.risk_agent import run_risk_agent, RiskConfig, CheckResult
from src.knowledge_base.multi_retriever import MultiRetriever, BM25Retriever, CrossEncoderReranker, RetrievalResult
from src.knowledge_base.chunker import QuantChunker, Chunk


# ── AgentMessage protocol tests ────────────────────────────────────


class TestAgentMessage:
    def test_creation_defaults(self):
        msg = AgentMessage()
        assert msg.status == "pending"
        assert msg.msg_id  # auto-generated
        assert msg.timestamp > 0

    def test_to_dict_roundtrip(self):
        msg = AgentMessage(
            payload={"query": "RSI strategy"},
            status="success",
            source_agent="retrieval",
            target_agent="reasoning",
            asset="BTC-USDT",
            timeframe="1h",
        )
        d = msg.to_dict()
        assert d["payload"]["query"] == "RSI strategy"
        assert d["status"] == "success"
        assert d["asset"] == "BTC-USDT"

        msg2 = AgentMessage.from_dict(d)
        assert msg2.payload["query"] == "RSI strategy"
        assert msg2.source_agent == "retrieval"

    def test_session_id_propagation(self):
        msg = AgentMessage(session_id="test-session-123")
        assert msg.session_id == "test-session-123"


# ── Retrieval Agent tests ──────────────────────────────────────────


class TestRetrievalAgent:
    def test_valid_query_returns_result(self):
        msg = AgentMessage(payload={"query": "RSI oversold strategy"})
        result = run_retrieval_agent(msg)
        assert result.status == "success"
        assert "has_valid_docs" in result.payload
        assert "reference_docs" in result.payload
        assert result.source_agent == "retrieval_agent"
        assert result.target_agent == "reasoning_agent"

    def test_empty_query_returns_error(self):
        msg = AgentMessage(payload={"query": ""})
        result = run_retrieval_agent(msg)
        assert result.status == "error"
        assert "query" in result.error_msg.lower()

    def test_missing_query_returns_error(self):
        msg = AgentMessage(payload={})
        result = run_retrieval_agent(msg)
        assert result.status == "error"

    def test_retrieval_preserves_metadata(self):
        msg = AgentMessage(
            payload={"query": "EMA crossover"},
            asset="ETH-USDT",
            timeframe="4h",
            session_id="session-xyz",
        )
        result = run_retrieval_agent(msg)
        assert result.asset == "ETH-USDT"
        assert result.timeframe == "4h"
        assert result.session_id == "session-xyz"

    def test_rsi_query_finds_rsi_docs(self):
        msg = AgentMessage(payload={"query": "RSI超卖反弹策略"})
        result = run_retrieval_agent(msg)
        # RSI is a strong keyword in the knowledge base
        assert result.payload["has_valid_docs"] is True
        assert len(result.payload["reference_docs"]) > 0


# ── Reasoning Agent tests ──────────────────────────────────────────


class TestReasoningAgent:
    def test_no_valid_docs_forces_neutral(self):
        """When has_valid_docs=false, reasoning MUST output neutral."""
        msg = AgentMessage(
            payload={
                "has_valid_docs": False,
                "reference_docs": [],
                "market_data": "BTC=$65000",
                "user_request": "Should I buy?",
            },
        )
        result = run_reasoning_agent(msg)
        intent = result.payload
        assert intent["view"] == "neutral"
        assert intent["confidence"] == 0.0
        assert intent["suggest_position_ratio"] == 0
        assert "无合格" in intent["reason"] or "置信度" in intent["reason"]

    def test_neutral_intent_helper(self):
        intent = _neutral_intent("test reason")
        assert intent["view"] == "neutral"
        assert intent["confidence"] == 0.0
        assert intent["reason"] == "test reason"

    def test_extract_json_from_fenced(self):
        text = '```json\n{"view": "long", "confidence": 0.7}\n```'
        result = _extract_json(text)
        assert result is not None
        assert result["view"] == "long"

    def test_extract_json_from_bare(self):
        text = 'Here is the result: {"view": "short", "confidence": 0.5}'
        result = _extract_json(text)
        assert result is not None
        assert result["view"] == "short"

    def test_extract_json_invalid(self):
        assert _extract_json("no json here") is None

    def test_reasoning_clamps_values(self):
        """Reasoning agent should clamp out-of-range values."""
        msg = AgentMessage(
            payload={
                "has_valid_docs": True,
                "reference_docs": [{"title": "Test", "content": "EMA strategy", "score": 0.8}],
                "market_data": "BTC=$65000",
                "user_request": "Buy BTC",
            },
        )
        result = run_reasoning_agent(msg)
        intent = result.payload
        assert 0.0 <= intent["confidence"] <= 1.0
        assert 0.0 <= intent["suggest_position_ratio"] <= 0.3
        assert intent["view"] in ("long", "short", "neutral")


# ── Risk Agent tests (the most critical) ───────────────────────────


class TestRiskAgent:
    def test_neutral_view_rejected(self):
        """Neutral view → allow_execute=False (no trade needed)."""
        msg = AgentMessage(payload={
            "view": "neutral",
            "confidence": 0.5,
            "suggest_position_ratio": 0.1,
            "stop_loss_price": None,
            "reason": "test",
        })
        result = run_risk_agent(msg)
        assert result.payload["allow_execute"] is False

    def test_low_confidence_rejected(self):
        """Confidence below threshold → rejected."""
        msg = AgentMessage(payload={
            "view": "long",
            "confidence": 0.15,  # Below default threshold 0.30
            "suggest_position_ratio": 0.1,
            "stop_loss_price": 63000,
            "entry_price": 65000,
            "reason": "EMA crossover",
        })
        result = run_risk_agent(msg)
        assert result.payload["allow_execute"] is False
        assert "confidence" in result.payload["checks_failed"]

    def test_position_exceeds_limit_auto_adjusted(self):
        """Position > max_per_asset → auto-adjusted down, not rejected."""
        msg = AgentMessage(payload={
            "view": "long",
            "confidence": 0.7,
            "suggest_position_ratio": 0.25,  # Exceeds 0.10 default
            "stop_loss_price": 63000,
            "entry_price": 65000,
            "reason": "Strong signal",
        })
        result = run_risk_agent(msg)
        assert result.payload["allow_execute"] is True
        assert result.payload["final_position_ratio"] == 0.10  # Adjusted to max

    def test_position_exceeds_total_limit_rejected(self):
        """Position > max_total_position → rejected."""
        config = RiskConfig(max_total_position=0.08, max_per_asset_position=0.10)
        msg = AgentMessage(payload={
            "view": "long",
            "confidence": 0.7,
            "suggest_position_ratio": 0.09,  # Below per-asset but above total
            "stop_loss_price": 63000,
            "entry_price": 65000,
            "reason": "test",
        })
        result = run_risk_agent(msg, config=config)
        assert result.payload["allow_execute"] is False
        assert "total_position" in result.payload["checks_failed"]

    def test_stop_loss_too_tight_rejected(self):
        """Stop loss distance < min → rejected."""
        config = RiskConfig(min_stop_loss_distance=0.02)
        msg = AgentMessage(payload={
            "view": "long",
            "confidence": 0.7,
            "suggest_position_ratio": 0.08,
            "stop_loss_price": 64900,  # Very tight
            "entry_price": 65000,
            "reason": "test",
        })
        result = run_risk_agent(msg, config=config)
        assert result.payload["allow_execute"] is False
        assert "stop_loss_distance" in result.payload["checks_failed"]

    def test_stop_loss_too_wide_rejected(self):
        """Stop loss distance > max → rejected."""
        config = RiskConfig(max_stop_loss_distance=0.10)
        msg = AgentMessage(payload={
            "view": "long",
            "confidence": 0.7,
            "suggest_position_ratio": 0.08,
            "stop_loss_price": 50000,  # Very wide (23%)
            "entry_price": 65000,
            "reason": "test",
        })
        result = run_risk_agent(msg, config=config)
        assert result.payload["allow_execute"] is False
        assert "stop_loss_distance" in result.payload["checks_failed"]

    def test_missing_stop_loss_rejected(self):
        """Non-neutral view without stop loss → rejected."""
        msg = AgentMessage(payload={
            "view": "long",
            "confidence": 0.7,
            "suggest_position_ratio": 0.08,
            "stop_loss_price": None,
            "reason": "test",
        })
        result = run_risk_agent(msg)
        assert result.payload["allow_execute"] is False
        assert "stop_loss_distance" in result.payload["checks_failed"]

    def test_missing_reason_rejected(self):
        """Empty reason → rejected."""
        msg = AgentMessage(payload={
            "view": "long",
            "confidence": 0.7,
            "suggest_position_ratio": 0.08,
            "stop_loss_price": 63000,
            "entry_price": 65000,
            "reason": "",
        })
        result = run_risk_agent(msg)
        assert result.payload["allow_execute"] is False
        assert "reason_completeness" in result.payload["checks_failed"]

    def test_all_checks_pass(self):
        """Valid intent with all checks passing → allow_execute=True."""
        msg = AgentMessage(payload={
            "view": "long",
            "confidence": 0.75,
            "suggest_position_ratio": 0.08,
            "stop_loss_price": 63000,
            "entry_price": 65000,
            "reason": "EMA crossover with volume confirmation",
        })
        result = run_risk_agent(msg)
        assert result.payload["allow_execute"] is True
        assert result.payload["final_position_ratio"] == 0.08
        assert len(result.payload["checks_failed"]) == 0

    def test_custom_config(self):
        """Custom RiskConfig changes limits."""
        config = RiskConfig(max_per_asset_position=0.05)
        msg = AgentMessage(payload={
            "view": "long",
            "confidence": 0.7,
            "suggest_position_ratio": 0.08,
            "stop_loss_price": 63000,
            "entry_price": 65000,
            "reason": "test",
        })
        result = run_risk_agent(msg, config=config)
        assert result.payload["final_position_ratio"] == 0.05  # Adjusted to custom max


# ── MultiRetriever tests ───────────────────────────────────────────


class TestMultiRetriever:
    def test_retrieve_returns_result(self):
        mr = MultiRetriever()
        result = mr.retrieve("RSI超卖策略")
        assert isinstance(result, RetrievalResult)
        assert isinstance(result.has_valid_docs, bool)
        assert isinstance(result.max_confidence_score, float)

    def test_retrieve_empty_query(self):
        mr = MultiRetriever()
        result = mr.retrieve("")
        assert result.has_valid_docs is False
        assert len(result.reference_docs) == 0

    def test_retrieve_with_filter(self):
        mr = MultiRetriever()
        result = mr.retrieve("EMA strategy", filter_meta={"asset": "BTC"})
        assert isinstance(result, RetrievalResult)

    def test_confidence_threshold(self):
        """Low-quality query should return has_valid_docs=False."""
        mr = MultiRetriever()
        result = mr.retrieve("xyz random nonsense query zzz")
        # Very unlikely to match any knowledge entry well
        assert isinstance(result.has_valid_docs, bool)

    def test_retrieve_as_context(self):
        mr = MultiRetriever()
        ctx = mr.retrieve_as_context("RSI strategy")
        # Should return some context for RSI
        assert isinstance(ctx, str)


# ── BM25 Retriever tests ───────────────────────────────────────────


class TestBM25Retriever:
    def test_retrieve_rsi(self):
        from src.knowledge_base.retriever import KnowledgeRetriever
        kr = KnowledgeRetriever()
        bm25 = BM25Retriever(kr._entries)
        results = bm25.retrieve("RSI oversold", top_k=5)
        assert len(results) > 0
        # RSI entry should be in top results
        titles = [entry.title for _, entry in results]
        assert any("RSI" in t for t in titles)

    def test_retrieve_empty_query(self):
        from src.knowledge_base.retriever import KnowledgeRetriever
        kr = KnowledgeRetriever()
        bm25 = BM25Retriever(kr._entries)
        results = bm25.retrieve("", top_k=5)
        assert len(results) == 0


# ── Chunker tests ──────────────────────────────────────────────────


class TestQuantChunker:
    def test_chunk_short_document(self):
        chunker = QuantChunker()
        text = "This is a short document about EMA crossover strategies. " * 10  # > MIN_CHUNK_CHARS
        chunks = chunker.chunk_document(text, metadata={"strategy_name": "EMA"})
        assert len(chunks) >= 1
        assert chunks[0].metadata["strategy_name"] == "EMA"

    def test_chunk_long_document(self):
        chunker = QuantChunker()
        text = "## EMA Strategy\n\n" + ("This is a paragraph about trading. " * 200)
        chunks = chunker.chunk_document(text, metadata={"doc_version": "v2.1"})
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.metadata["doc_version"] == "v2.1"
            assert chunk.metadata["total_chunks"] == len(chunks)

    def test_table_preserved(self):
        chunker = QuantChunker()
        text = "## Strategy Rules\n\n| Indicator | Period | Usage |\n|-----------|--------|-------|\n| EMA | 20 | Fast |\n| EMA | 50 | Slow |\n\nSome text after."
        chunks = chunker.chunk_document(text)
        # Table should be a separate chunk
        table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table"]
        assert len(table_chunks) >= 1

    def test_chunk_metadata(self):
        chunker = QuantChunker()
        chunks = chunker.chunk_document(
            "Short text about BTC strategy. " * 15,
            metadata={"strategy_name": "BTC_EMA", "asset": "BTC", "timeframe": "1h"},
        )
        assert len(chunks) >= 1
        assert chunks[0].metadata["asset"] == "BTC"
        assert chunks[0].metadata["timeframe"] == "1h"
        assert "chunk_index" in chunks[0].metadata
