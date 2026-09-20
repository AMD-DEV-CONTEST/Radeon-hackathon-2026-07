"""Intent classifier — three-way routing (strategy / compute / query).

The key review fix: distinguish "retrieval" from "computation" BEFORE
anything hits RAG. Strategy generation keeps going to the DSL pipeline;
local computation stays local (factors, VaR, backtests, indicators —
never touch the network); only information queries consult RAG and,
on miss, fall back to external tools.

Deterministic keyword rules (no LLM call), mirroring the style of
`src/agent/personality.py::is_trading_intent` but with 4 buckets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Intent buckets ──────────────────────────────────────────────────

STRATEGY_GENERATION = "strategy_generation"   # → existing DSL pipeline
LOCAL_COMPUTE = "local_compute"               # → local factor/risk/backtest tools
INFO_QUERY = "info_query"                     # → RAG → external tools on miss
GENERAL = "general"                           # → personality chat

# ── Keyword sets (whitelist, ordered by precedence) ─────────────────

# Precedence: a "strategy" word beats a "compute" word beats a "query" word.
# E.g. "回测" is a strategy-generation trigger; "算一下最大回撤" is compute.

_STRATEGY_WORDS = [
    "策略", "回测", "均线", "MACD", "RSI", "KDJ", "布林", "金叉", "死叉",
    "突破", "止损", "止盈", "建仓", "开仓", "平仓", "仓位", "仓位管理",
    "指标", "K线", "K线图", "设计", "写一个", "生成策略", "DSL",
    "strategy", "backtest", "indicator", "crossover", "stop loss",
]
_COMPUTE_WORDS = [
    "VaR", "CVaR", "夏普", "Sortino", "索提诺", "Calmar", "回撤", "最大回撤",
    "有效前沿", "风险平价", "Black-Litterman", "均值方差", "波动率", "年化",
    "期权", "Black-Scholes", "Greeks", "Delta", "Gamma", "Vega", "Theta",
    "隐含波动率", "因子", "ICIR", "IC值", "协整", "配对", "回归", "相关性",
    "计算", "算一下", "算算", "测算", "胜率", "盈亏比", "信息比率",
    "factor", "portfolio", "optimization", "sharpe", "drawdown", "correlation",
]
_QUERY_WORDS = [
    "行情", "价格", "股价", "最新价", "走势", "收盘", "开盘", "涨跌", "涨幅",
    "成交额", "成交量", "市盈率", "PE", "PB", "市净率", "分红", "股息",
    "公告", "新闻", "财报", "业绩", "披露", "涨停", "跌停", "换手",
    "宏观", "GDP", "CPI", "利率", "汇率", "美联储", "议息", "政策",
    "查询", "查一下", "看看", "信息", "数据", "是多少", "现价",
    "规则", "制度", "约束", "什么是", "允许", "禁止", "T+1",
    "news", "announcement", "price", "quote", "market data", "macro",
]
_GENERAL_WORDS = ["你好", "你是谁", "介绍一下", "谢谢", "再见", "hi", "hello"]

# Symbols of the four A-share ETFs used in the project — the mock data
# provider serves deterministic synthetic OHLCV for these.
SUPPORTED_SYMBOLS = {"510300.SH", "510050.SH", "510500.SH", "159915.SZ"}


@dataclass
class IntentDecision:
    intent: str
    confidence: float
    hints: list[str]

    def to_dict(self) -> dict:
        return {"intent": self.intent, "confidence": round(self.confidence, 2), "hints": self.hints}


def classify_intent(text: str) -> IntentDecision:
    """Classify a user message into one of the four buckets."""
    if not text or not text.strip():
        return IntentDecision(GENERAL, 1.0, [])

    def _hits(words: list[str]) -> list[str]:
        lower = text.lower()
        return [w for w in words if w.lower() in lower]

    # Precedence: strategy > compute > query > general
    for bucket, words in (
        (STRATEGY_GENERATION, _STRATEGY_WORDS),
        (LOCAL_COMPUTE, _COMPUTE_WORDS),
        (INFO_QUERY, _QUERY_WORDS),
    ):
        hits = _hits(words)
        if hits:
            conf = min(0.99, 0.80 + 0.06 * min(len(hits), 3))
            return IntentDecision(bucket, conf, hits[:5])

    if _hits(_GENERAL_WORDS):
        return IntentDecision(GENERAL, 0.9, [])

    return IntentDecision(GENERAL, 0.6, [])
