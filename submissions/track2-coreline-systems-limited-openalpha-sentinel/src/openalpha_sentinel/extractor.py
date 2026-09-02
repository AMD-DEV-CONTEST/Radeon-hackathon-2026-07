from __future__ import annotations

import re
from collections.abc import Iterable

from .schemas import Chunk, EvidenceRef, FetchedArtifact, StrategyCard
from .utils import first_nonempty_line, normalize_text, sha256_text, stable_json


TYPE_KEYWORDS = {
    "mean reversion": ("mean reversion", "mean-reversion", "均值回归"),
    "momentum": ("momentum", "trend following", "trend-following", "动量", "趋势跟踪"),
    "pairs trading": ("pairs trading", "pair trading", "statistical arbitrage", "配对交易", "统计套利"),
    "arbitrage": ("arbitrage", "套利"),
    "market making": ("market making", "做市"),
    "factor investing": ("factor", "fama-french", "因子", "多因子"),
    "breakout": ("breakout", "channel breakout", "突破"),
    "machine learning": ("machine learning", "xgboost", "neural network", "机器学习", "神经网络"),
}

MARKET_KEYWORDS = {
    "crypto": ("crypto", "bitcoin", "ethereum", "btc", "eth", "加密货币", "数字货币"),
    "equities": ("equity", "equities", "stock", "stocks", "s&p", "nasdaq", "股票", "美股", "a股"),
    "futures": ("future", "futures", "期货"),
    "forex": ("forex", "foreign exchange", "fx ", "外汇"),
    "options": ("option", "options", "期权"),
    "etf": ("etf", "exchange-traded fund"),
}

SIGNAL_KEYWORDS = {
    "RSI": ("rsi", "relative strength index"),
    "moving average": ("moving average", "sma", "ema", "移动平均", "均线"),
    "z-score": ("z-score", "zscore", "z score"),
    "Bollinger Bands": ("bollinger", "布林"),
    "breakout": ("breakout", "突破"),
    "cointegration": ("cointegration", "协整"),
    "volatility": ("volatility", "波动率"),
    "volume": ("volume", "成交量"),
}

COST_KEYWORDS = (
    "transaction cost",
    "transaction costs",
    "trading cost",
    "trading costs",
    "commission",
    "slippage",
    "手续费",
    "交易成本",
    "滑点",
)


def _find_values(text: str, mapping: dict[str, tuple[str, ...]]) -> list[str]:
    return [
        name
        for name, keywords in mapping.items()
        if any(_contains_keyword(text, keyword) for keyword in keywords)
    ]


def _contains_keyword(text: str, keyword: str) -> bool:
    keyword = keyword.strip()
    if not keyword:
        return False

    prefix = (
        r"(?<![A-Za-z0-9_-])"
        if keyword[0].isascii() and keyword[0].isalnum()
        else ""
    )
    suffix = (
        r"(?![A-Za-z0-9_-])"
        if keyword[-1].isascii() and keyword[-1].isalnum()
        else ""
    )
    escaped = r"\s+".join(re.escape(part) for part in keyword.split())
    return re.search(f"{prefix}{escaped}{suffix}", text, re.I) is not None


def _first_matching_chunk(chunks: Iterable[Chunk], keywords: Iterable[str]) -> Chunk | None:
    keywords = tuple(keywords)
    for chunk in chunks:
        if any(_contains_keyword(chunk.text, keyword) for keyword in keywords):
            return chunk
    return None


def _source_with_lines(url: str, start: int, end: int) -> str:
    if "github.com/" in url and "/blob/" in url:
        return f"{url.split('#', 1)[0]}#L{start}-L{end}"
    return url


class RuleBasedExtractor:
    """Deterministic extraction keeps the local demo useful before a model is available."""

    name = "rules-v1"

    def extract(
        self,
        artifact: FetchedArtifact,
        source_id: str,
        revision_id: str,
        chunks: list[Chunk],
        chunk_source_urls: dict[str, str] | None = None,
    ) -> StrategyCard:
        chunk_source_urls = chunk_source_urls or {}

        chunks = [
            chunk
            for chunk in chunks
            if any(character.isalnum() for character in normalize_text(chunk.text))
        ]
        if not chunks:
            raise ValueError("Source did not contain usable text for extraction")

        def evidence_url(chunk: Chunk) -> str:
            return chunk_source_urls.get(chunk.id, artifact.immutable_url)

        full_text = normalize_text("\n\n".join(chunk.text for chunk in chunks))
        title = artifact.title.strip() or first_nonempty_line(full_text)
        strategy_types = _find_values(full_text, TYPE_KEYWORDS)
        markets = _find_values(full_text, MARKET_KEYWORDS)
        signals = _find_values(full_text, SIGNAL_KEYWORDS)
        timeframes = self._timeframes(full_text)
        summary = self._summary(full_text, title)
        cost_statement_text = re.sub(r"\s+", " ", full_text)
        explicit_cost_omission = bool(
            re.search(
                r"(?:does not|doesn't|did not|not)\s+(?:explicitly\s+)?disclos(?:e|ed)"
                r"[^.\n]{0,80}(?:transaction costs?|commission|slippage)"
                r"|(?:未|没有|并未)[^。\n]{0,20}(?:披露|说明)[^。\n]{0,30}(?:交易成本|手续费|滑点)",
                cost_statement_text,
                re.I,
            )
        )
        cost_chunk = _first_matching_chunk(chunks, COST_KEYWORDS)
        if explicit_cost_omission:
            cost_disclosure = "not_disclosed"
        elif cost_chunk:
            cost_disclosure = "disclosed"
        else:
            cost_disclosure = "unknown"

        risk_flags: list[str] = []
        if cost_disclosure == "not_disclosed":
            risk_flags.append("transaction_cost_not_disclosed")
        if not re.search(r"\b(?:19|20)\d{2}\b|backtest period|test period|回测区间|样本期", full_text, re.I):
            risk_flags.append("backtest_period_not_disclosed")
        if artifact.license_spdx in {"", "NOASSERTION", "UNKNOWN", "unknown"}:
            risk_flags.append("license_unknown")
        if re.search(r"look[ -]?ahead|future data|data leakage|前视偏差|未来数据|数据泄漏", full_text, re.I):
            risk_flags.append("bias_risk_discussed")

        evidence: list[EvidenceRef] = []
        if chunks:
            evidence.append(self._evidence("summary", chunks[0], evidence_url(chunks[0])))
        if strategy_types:
            chunk = _first_matching_chunk(chunks, TYPE_KEYWORDS[strategy_types[0]])
            if chunk:
                evidence.append(self._evidence("strategy_type", chunk, evidence_url(chunk)))
        for market in markets[:3]:
            chunk = _first_matching_chunk(chunks, MARKET_KEYWORDS[market])
            if chunk:
                evidence.append(self._evidence("markets", chunk, evidence_url(chunk)))
        for signal in signals[:4]:
            chunk = _first_matching_chunk(chunks, SIGNAL_KEYWORDS[signal])
            if chunk:
                evidence.append(self._evidence("signals", chunk, evidence_url(chunk)))
        if cost_chunk:
            evidence.append(self._evidence("cost_disclosure", cost_chunk, evidence_url(cost_chunk)))
        license_chunk = _first_matching_chunk(chunks, ("license", "许可", artifact.license_spdx))
        if license_chunk:
            evidence.append(self._evidence("license_spdx", license_chunk, evidence_url(license_chunk)))

        fingerprint = sha256_text(
            stable_json(
                {
                    "title": title.lower(),
                    "type": strategy_types[0] if strategy_types else "unknown",
                    "markets": markets,
                    "signals": signals,
                }
            )
        )
        return StrategyCard(
            source_id=source_id,
            revision_id=revision_id,
            title=title[:200],
            summary=summary,
            strategy_type=strategy_types[0] if strategy_types else "unknown",
            markets=markets,
            timeframes=timeframes,
            signals=signals,
            license_spdx=artifact.license_spdx or "NOASSERTION",
            cost_disclosure=cost_disclosure,
            risk_flags=risk_flags,
            source_url=artifact.canonical_url,
            immutable_url=artifact.immutable_url,
            revision_key=artifact.revision_key,
            author=artifact.author,
            evidence=evidence,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _summary(text: str, title: str) -> str:
        paragraphs = re.split(r"\n\s*\n", text)
        for paragraph in paragraphs:
            if paragraph.lstrip().startswith("#"):
                continue
            clean = re.sub(r"^[#>*\-\s]+", "", paragraph).strip()
            if clean and clean.lower() != title.lower() and len(clean) >= 40:
                return re.sub(r"\s+", " ", clean)[:500]
        return re.sub(r"\s+", " ", text)[:500] or "No source summary was available."

    @staticmethod
    def _timeframes(text: str) -> list[str]:
        patterns = {
            "intraday": r"intraday|分钟|小时|minute|hourly",
            "daily": r"\bdaily\b|\b1d\b|日线|每日",
            "weekly": r"\bweekly\b|\b1w\b|周线|每周",
            "monthly": r"\bmonthly\b|\b1m\b|月线|每月",
        }
        return [name for name, pattern in patterns.items() if re.search(pattern, text, re.I)]

    @staticmethod
    def _evidence(field: str, chunk: Chunk, url: str) -> EvidenceRef:
        quote = re.sub(r"\s+", " ", chunk.text).strip()[:300]
        return EvidenceRef(
            field=field,
            chunk_id=chunk.id,
            quote=quote,
            source_url=_source_with_lines(url, chunk.start_line, chunk.end_line),
            line_start=chunk.start_line,
            line_end=chunk.end_line,
        )
