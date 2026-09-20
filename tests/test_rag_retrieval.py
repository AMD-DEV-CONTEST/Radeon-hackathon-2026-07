"""Tests for the RAG knowledge base retriever.

These are pure-CPU (no Genesis, no embeddings). They verify:
  - alias expansion fixes recall (横盘 -> Mean Reversion, 双均线 -> MA Crossover)
  - Chinese multi-char matching (no single-char false positives)
  - funding rate / new entries are retrievable
  - backward-compatible regression: BTC RSI query still returns the right trio
  - the optional semantic module imports safely without sentence-transformers
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.knowledge_base.retriever import KnowledgeRetriever
from src.knowledge_base import semantic


def _titles(res):
    return [e.title for e in res]


def test_alias_hengpan_recalls_mean_reversion():
    kr = KnowledgeRetriever()
    res = kr.retrieve("市场横盘时该怎么操作", max_results=5)
    titles = _titles(res)
    assert "Mean Reversion: RSI / Bollinger Bands" in titles, titles
    # Regime entry should also surface for 横盘.
    assert "Market Regime Classification" in titles, titles


def test_alias_shuangjunxian_recalls_ma_crossover():
    kr = KnowledgeRetriever()
    res = kr.retrieve("我想做双均线交叉交易", max_results=5)
    assert "Trend Following: MA Crossover" in _titles(res), _titles(res)


def test_funding_rate_query_recalls_funding_entry():
    kr = KnowledgeRetriever()
    res = kr.retrieve("永续合约的资金费率怎么看", max_results=6)
    assert "Funding Rate (Perpetual Swaps)" in _titles(res), _titles(res)


def test_no_single_char_false_positive():
    # A lone common char "云" must NOT over-recall many entries.
    kr = KnowledgeRetriever()
    res = kr.retrieve("云", max_results=10, min_score=0.1)
    # "云" is not a term in any entry (we deliberately ignore single chars).
    assert res == [], _titles(res)


def test_cn_unit_match_not_char_fragment():
    # 以太坊 must match the ETH entry as a UNIT, not via 以/太/坊 fragments
    # bleeding into unrelated entries.
    kr = KnowledgeRetriever()
    res = kr.retrieve("以太坊 突破 放量", max_results=5)
    titles = _titles(res)
    assert "ETH Market Characteristics" in titles, titles
    assert "Volume-Confirmed Breakout" in titles, titles


def test_regression_btc_rsi_stoploss():
    kr = KnowledgeRetriever()
    res = kr.retrieve("BTC RSI超卖 止损3%", max_results=4)
    titles = _titles(res)
    assert "RSI (Relative Strength Index)" in titles, titles
    assert "Stop-Loss Best Practices" in titles, titles
    assert "BTC Market Characteristics" in titles, titles


def test_new_entries_present():
    kr = KnowledgeRetriever()
    all_titles = {e.title for e in kr._entries}
    for expected in [
        "Funding Rate (Perpetual Swaps)",
        "Market Regime Classification",
        "Drawdown & Portfolio Risk Control",
        "SOL Market Characteristics",
        "BNB Market Characteristics",
        "Backtest Validity & Overfitting",
        "Correlation & Diversification",
        "DCA (Dollar-Cost Averaging)",
    ]:
        assert expected in all_titles, f"missing entry: {expected}"


def test_total_entry_count():
    kr = KnowledgeRetriever()
    # 23 original + 8 existing additions + 2 DSL contract entries = 33
    assert len(kr._entries) == 33, len(kr._entries)


def test_semantic_module_imports_safe_without_deps():
    # semantic_available() must be callable and return a bool even if
    # sentence-transformers is not installed (fail-safe design).
    assert isinstance(semantic.semantic_available(), bool)


def test_retrieve_as_context_groups_by_category():
    kr = KnowledgeRetriever()
    ctx = kr.retrieve_as_context("BTC RSI超卖 止损3%", max_results=4)
    assert "## Indicator" in ctx or "## Risk" in ctx, ctx[:200]
    assert "RSI (Relative Strength Index)" in ctx
