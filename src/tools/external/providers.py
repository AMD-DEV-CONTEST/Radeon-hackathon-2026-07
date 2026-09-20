"""External data providers — market_data & announcement, mock/real dual mode.

Per the approved scope:
- `mock` is the DEFAULT (deterministic synthetic data, zero network, fully
  reproducible for judging and CI).
- `real` is opt-in (akshare backend); if akshare is missing or the call
  fails, the provider DEGRADES to mock and marks `data_mode=mock_fallback`
  instead of crashing — this is the graceful-degradation guarantee.
- Review rule: mock data is explicitly labeled synthetic with LOW source
  confidence (0.4) and a limitation notice, so the agent never passes it
  off as real market data.
"""

from __future__ import annotations

import os
import random
from datetime import date, datetime, timedelta

from .protocol import ToolResult, SOURCE_CONFIDENCE, now_iso, ttl_iso, tools_mode

# ── Mock data (deterministic: same symbol+days → same series) ───────


def _mock_ohlcv(symbol: str, days: int) -> list[dict]:
    rng = random.Random(f"{symbol}:{days}")
    price = 3.60 if symbol.startswith("510") else 2.10  # ETF 量级
    rows: list[dict] = []
    today = date.today()
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        open_ = price
        close = round(open_ * (1 + rng.uniform(-0.025, 0.025)), 3)
        high = round(max(open_, close) * (1 + rng.uniform(0, 0.01)), 3)
        low = round(min(open_, close) * (1 - rng.uniform(0, 0.01)), 3)
        volume = int(rng.uniform(1_000_000, 6_000_000))
        rows.append({
            "date": d.isoformat(),
            "open": open_, "close": close, "high": high, "low": low,
            "volume": volume,
        })
        price = close
    return rows


def _mock_announcements(symbol: str) -> list[dict]:
    return [
        {"date": (date.today() - timedelta(days=2)).isoformat(),
         "title": f"{symbol} 关于召开年度股东大会的通知", "type": "股东大会"},
        {"date": (date.today() - timedelta(days=9)).isoformat(),
         "title": f"{symbol} 2026 年半年度业绩预告", "type": "业绩预告"},
        {"date": (date.today() - timedelta(days=15)).isoformat(),
         "title": f"{symbol} 权益分派实施公告", "type": "分红送转"},
    ]


# ── Mock search: deterministic, quant-domain flavored ───────────────

_SEARCH_TEMPLATES = [
    ("东方财富", "市场要闻", "沪深两市今日震荡整理，沪指收涨 0.42%，两市成交额 1.1 万亿元。"),
    ("中国证券报", "宏观政策", "央行发布最新货币政策执行报告，强调稳健取向与跨周期调节。"),
    ("Wind 资讯", "行业研究", "机构观点：A 股红利与科技双主线，宽基 ETF 持续获资金净流入。"),
    ("证券时报", "公司公告", "多家上市公司发布半年度业绩预告，半导体与 AI 算力板块预增居前。"),
    ("新华财经", "海外市场", "美联储官员表态偏鸽，美债收益率回落，黄金短线走高。"),
]


def _mock_search_results(query: str) -> list[dict]:
    rng = random.Random(f"search:{query}")
    picked = rng.sample(_SEARCH_TEMPLATES, k=min(4, len(_SEARCH_TEMPLATES)))
    rows = []
    for i, (source, _type, summary) in enumerate(picked):
        rows.append({
            "title": f"[{_type}] {summary[:18]}…",
            "source": source,
            "summary": summary,
            "date": (date.today() - timedelta(days=i)).isoformat(),
            "url": f"https://example.com/res/{abs(hash(query)) % 10000 + i}",
        })
    return rows


# ── Real providers (akshare / tavily, optional) ─────────────────────


def _real_market_data(symbol: str, days: int) -> ToolResult | None:
    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return None
    try:
        code = symbol.split(".")[0]
        df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
        df = df.tail(days)
        rows = [{
            "date": str(r["日期"]), "open": float(r["开盘"]),
            "close": float(r["收盘"]), "high": float(r["最高"]),
            "low": float(r["最低"]), "volume": int(r["成交量"]),
        } for _, r in df.iterrows()]
        return ToolResult(
            success=True, tool="market_data", source="AKShare (real)",
            source_confidence=SOURCE_CONFIDENCE["aggregator"],
            relevance_score=0.95, data_mode="public_snapshot",
            data={"symbol": symbol, "days": days, "rows": rows},
            effective_until=ttl_iso(15),
            limitations=["免费聚合源，行情可能有分钟级延迟", "A股历史数据以交易所披露为准"],
        )
    except Exception as exc:  # pragma: no cover - network/data issues
        return ToolResult(
            success=False, tool="market_data", source="AKShare (real)",
            source_confidence=SOURCE_CONFIDENCE["aggregator"],
            relevance_score=0.0, data_mode="public_snapshot",
            data={"error": str(exc)[:200]},
            limitations=[f"real 数据获取失败，可切换 mock 模式演示"],
        )


def _real_announcement(symbol: str) -> ToolResult | None:
    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return None
    try:
        code = symbol.split(".")[0]
        df = ak.stock_zh_a_disclosure_report_cninfo(symbol=code, symbol_type="沪深A股")
        df = df.head(5)
        rows = [{"date": str(r.get("公告日期", "")), "title": str(r.get("公告标题", ""))}
                for _, r in df.iterrows()]
        return ToolResult(
            success=True, tool="announcement", source="AKShare/巨潮 (real)",
            source_confidence=SOURCE_CONFIDENCE["aggregator"],
            relevance_score=0.9, data_mode="public_snapshot",
            data={"symbol": symbol, "rows": rows}, effective_until=ttl_iso(60 * 24),
            limitations=["公告接口字段随 akshare 版本可能变化"],
        )
    except Exception as exc:  # pragma: no cover
        return ToolResult(
            success=False, tool="announcement", source="AKShare (real)",
            source_confidence=SOURCE_CONFIDENCE["aggregator"],
            relevance_score=0.0, data_mode="public_snapshot",
            data={"error": str(exc)[:200]},
            limitations=["real 公告获取失败，已触发降级"],
        )


def _real_search(query: str) -> ToolResult | None:
    """Tavily search backend (opt-in via TAVILY_API_KEY). Degrades to mock."""
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import httpx
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 5, "search_depth": "basic"},
            timeout=10.0,
        )
        resp.raise_for_status()
        items = resp.json().get("results", [])
        rows = [{
            "title": it.get("title", ""),
            "source": (it.get("url", "") or "").split("/")[2] if it.get("url") else "web",
            "summary": (it.get("content", "") or "")[:200],
            "url": it.get("url", ""),
        } for it in items]
        return ToolResult(
            success=True, tool="search", source="Tavily (real)",
            source_confidence=SOURCE_CONFIDENCE["aggregator"],
            relevance_score=0.7, data_mode="public_snapshot",
            data={"query": query, "rows": rows}, effective_until=ttl_iso(60 * 6),
            limitations=["搜索结果为网页摘要，需二次核验原始来源", "存在时效与来源质量差异"],
        )
    except Exception as exc:  # pragma: no cover - network
        return ToolResult(
            success=False, tool="search", source="Tavily (real)",
            source_confidence=SOURCE_CONFIDENCE["aggregator"],
            relevance_score=0.0, data_mode="public_snapshot",
            data={"error": str(exc)[:200]}, limitations=["搜索失败，可切换 mock 模式"],
        )


# ── Public providers ────────────────────────────────────────────────


def market_data(symbol: str = "510300.SH", days: int = 30, mode: str | None = None) -> ToolResult:
    """Return a ToolResult for daily OHLCV of an A-share symbol."""
    mode = (mode or tools_mode()).lower()
    if mode == "real":
        real = _real_market_data(symbol, days)
        if real is not None and real.success:
            return real

    rows = _mock_ohlcv(symbol, days)
    last = rows[-1] if rows else {}
    return ToolResult(
        success=True, tool="market_data", source="Deterministic synthetic (mock)",
        source_confidence=SOURCE_CONFIDENCE["mock"],
        relevance_score=0.9 if symbol in {"510300.SH", "510050.SH", "510500.SH", "159915.SZ"} else 0.55,
        data_mode="mock_fallback" if (mode == "real" and real is not None) else "mock",
        data={
            "symbol": symbol, "days": days,
            "last_close": last.get("close"), "last_date": last.get("date"),
            "rows": rows,
        },
        effective_until=ttl_iso(5),
        limitations=["合成演示数据，非真实行情", "仅用于系统闭环演示，不构成投资建议"],
    )


def announcement(symbol: str = "510300.SH", mode: str | None = None) -> ToolResult:
    """Return a ToolResult for recent announcements of a symbol."""
    mode = (mode or tools_mode()).lower()
    if mode == "real":
        real = _real_announcement(symbol)
        if real is not None and real.success:
            return real

    return ToolResult(
        success=True, tool="announcement", source="Deterministic synthetic (mock)",
        source_confidence=SOURCE_CONFIDENCE["mock"],
        relevance_score=0.85,
        data_mode="mock_fallback" if (mode == "real" and real is not None) else "mock",
        data={"symbol": symbol, "rows": _mock_announcements(symbol)},
        effective_until=ttl_iso(60 * 24),
        limitations=["合成演示数据，非真实公告"],
    )


def search(query: str, mode: str | None = None) -> ToolResult:
    """Return a ToolResult with web-search-style results for an info query."""
    mode = (mode or tools_mode()).lower()
    if mode == "real":
        real = _real_search(query)
        if real is not None and real.success:
            return real

    return ToolResult(
        success=True, tool="search", source="Deterministic synthetic (mock)",
        source_confidence=SOURCE_CONFIDENCE["mock"],
        relevance_score=0.7,
        data_mode="mock_fallback" if (mode == "real" and real is not None) else "mock",
        data={"query": query, "rows": _mock_search_results(query)},
        effective_until=ttl_iso(60 * 6),
        limitations=["合成演示结果，非真实网络检索", "仅用于展示搜索工具调用链路"],
    )
