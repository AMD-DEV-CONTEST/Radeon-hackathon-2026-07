from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

import requests


US_EQUITY_SOURCE_NAME = "Yahoo Finance market data and SEC company disclosures"
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_MARKET_INDEX_RE = re.compile(r"^\^[A-Z0-9.-]{1,9}$")
_SEC_CONCEPT_GROUPS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss",),
    "assets": ("Assets",),
    "stockholders_equity": ("StockholdersEquity",),
    "diluted_eps": ("EarningsPerShareDiluted",),
    "operating_income": ("OperatingIncomeLoss",),
}


class USMarketDataError(RuntimeError):
    """Raised when a U.S. market-data response is unavailable or malformed."""


class USMarketDataClient:
    _CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    _SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    _SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
    _SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    _MAX_ATTEMPTS = 3
    _REQUEST_TIMEOUT = (5, 20)
    _DEFAULT_SEC_USER_AGENT = "FastAgentFactory 2775965605@qq.com"

    def __init__(self) -> None:
        self._session = self._new_session()
        self._retry_count = 0
        self._request_count = 0
        self._hosts_used: set[str] = set()
        self._ticker_index: dict[str, dict[str, Any]] | None = None

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "USMarketDataClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        self.close()

    def quote(self, ticker: str) -> dict[str, Any]:
        symbol = market_symbol(ticker)
        result = self._chart_result(symbol, range="5d", interval="1d")
        meta = result.get("meta")
        if not isinstance(meta, dict):
            raise USMarketDataError(f"Yahoo Finance returned no quote metadata for {symbol}")
        price = _number(meta.get("regularMarketPrice"))
        previous_close = _number(meta.get("chartPreviousClose"))
        change = price - previous_close if price is not None and previous_close is not None else None
        change_pct = change / previous_close * 100 if change is not None and previous_close else None
        return {
            "ticker": symbol,
            "name": str(meta.get("longName") or meta.get("shortName") or symbol),
            "exchange": str(meta.get("fullExchangeName") or meta.get("exchangeName") or ""),
            "instrument_type": str(meta.get("instrumentType") or ""),
            "currency": str(meta.get("currency") or "USD"),
            "price": price,
            "previous_close": previous_close,
            "change": _number(change),
            "change_pct": _number(change_pct),
            "market_state": str(meta.get("marketState") or ""),
            "quote_time": _utc_timestamp(meta.get("regularMarketTime")),
        }

    def history(self, ticker: str, *, count: int, adjustment: str = "adjusted") -> list[dict[str, Any]]:
        if not 1 <= count <= 1000:
            raise ValueError("history count must be between 1 and 1000")
        if adjustment not in {"adjusted", "none"}:
            raise ValueError("history adjustment must be adjusted or none")
        symbol = market_symbol(ticker)
        period2 = datetime.now(UTC) + timedelta(days=1)
        period1 = period2 - timedelta(days=max(14, int(count * 1.8) + 10))
        result = self._chart_result(
            symbol,
            period1=int(period1.timestamp()),
            period2=int(period2.timestamp()),
            interval="1d",
        )
        timestamps = result.get("timestamp")
        indicators = result.get("indicators")
        quote_rows = indicators.get("quote") if isinstance(indicators, dict) else None
        adjusted_rows = indicators.get("adjclose") if isinstance(indicators, dict) else None
        quote = quote_rows[0] if isinstance(quote_rows, list) and quote_rows else None
        adjusted = adjusted_rows[0] if isinstance(adjusted_rows, list) and adjusted_rows else None
        if not isinstance(timestamps, list) or not isinstance(quote, dict):
            raise USMarketDataError(f"Yahoo Finance returned no price history for {symbol}")
        closes = adjusted.get("adjclose") if adjustment == "adjusted" and isinstance(adjusted, dict) else None
        if not isinstance(closes, list):
            closes = quote.get("close")
        rows: list[dict[str, Any]] = []
        for index, raw_timestamp in enumerate(timestamps):
            close = _sequence_number(closes, index)
            if close is None:
                continue
            rows.append({
                "date": datetime.fromtimestamp(int(raw_timestamp), UTC).date().isoformat(),
                "open": _sequence_number(quote.get("open"), index),
                "close": close,
                "high": _sequence_number(quote.get("high"), index),
                "low": _sequence_number(quote.get("low"), index),
                "volume": _sequence_number(quote.get("volume"), index),
            })
        if not rows:
            raise USMarketDataError(f"Yahoo Finance returned an empty price history for {symbol}")
        return rows[-count:]

    def screener(self, screen_id: str, *, count: int) -> list[dict[str, Any]]:
        if screen_id not in {"day_gainers", "day_losers", "most_actives"}:
            raise ValueError(f"unsupported Yahoo Finance screener: {screen_id}")
        if not 1 <= count <= 100:
            raise ValueError("screener count must be between 1 and 100")
        payload = self._request_json(
            self._SCREENER_URL,
            {"formatted": "false", "scrIds": screen_id, "count": str(count)},
        )
        finance = payload.get("finance")
        results = finance.get("result") if isinstance(finance, dict) else None
        quotes = results[0].get("quotes") if isinstance(results, list) and results else None
        if not isinstance(quotes, list):
            raise USMarketDataError(f"Yahoo Finance returned no {screen_id} rows")
        return [_screener_row(item) for item in quotes if isinstance(item, dict) and item.get("symbol")]

    def company_facts(self, ticker: str, *, limit: int = 12) -> list[dict[str, Any]]:
        symbol = us_equity_ticker(ticker)
        company = self._sec_company(symbol)
        payload = self._request_json(self._SEC_FACTS_URL.format(cik=f"{int(company['cik']):010d}"), None)
        facts = payload.get("facts")
        us_gaap = facts.get("us-gaap") if isinstance(facts, dict) else None
        if not isinstance(us_gaap, dict):
            raise USMarketDataError(f"SEC company facts are unavailable for {symbol}")
        records: list[dict[str, Any]] = []
        for metric, concepts in _SEC_CONCEPT_GROUPS.items():
            candidates = [
                (concept, fact, unit, item)
                for concept in concepts
                for fact in [us_gaap.get(concept)]
                if isinstance(fact, dict)
                for units in [fact.get("units")]
                if isinstance(units, dict)
                for unit, values in units.items()
                if isinstance(values, list)
                for item in values
                if isinstance(item, dict)
                and item.get("form") in {"10-K", "10-Q"}
                and item.get("filed")
            ]
            if not candidates:
                continue
            concept, fact, unit, latest = max(
                candidates,
                key=lambda candidate: (
                    str(candidate[3].get("filed")),
                    str(candidate[3].get("end")),
                    -concepts.index(candidate[0]),
                ),
            )
            records.append({
                "metric": metric,
                "concept": concept,
                "label": str(fact.get("label") or concept),
                "value": _number(latest.get("val")),
                "unit": unit,
                "form": str(latest.get("form") or ""),
                "period_end": str(latest.get("end") or ""),
                "filed_at": str(latest.get("filed") or ""),
                "accession_number": str(latest.get("accn") or ""),
            })
        return records[:limit]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": "yahoo_finance_and_sec",
            "hosts_used": sorted(self._hosts_used),
            "retry_count": self._retry_count,
            "requests_completed": self._request_count,
        }

    def _chart_result(self, ticker: str, **params: Any) -> dict[str, Any]:
        payload = self._request_json(
            self._CHART_URL.format(symbol=ticker),
            {key: str(value) for key, value in params.items()},
        )
        chart = payload.get("chart")
        error = chart.get("error") if isinstance(chart, dict) else None
        results = chart.get("result") if isinstance(chart, dict) else None
        if error or not isinstance(results, list) or not results:
            description = error.get("description") if isinstance(error, dict) else "no result"
            raise USMarketDataError(f"Yahoo Finance {ticker} request failed: {description}")
        return results[0]

    def _sec_company(self, ticker: str) -> dict[str, Any]:
        if self._ticker_index is None:
            payload = self._request_json(self._SEC_TICKERS_URL, None)
            self._ticker_index = {
                str(item.get("ticker") or "").upper().replace(".", "-"): {
                    "cik": item.get("cik_str"), "title": item.get("title")
                }
                for item in payload.values()
                if isinstance(item, dict) and item.get("ticker") and item.get("cik_str") is not None
            }
        company = self._ticker_index.get(ticker)
        if company is None:
            raise USMarketDataError(f"SEC ticker mapping is unavailable for {ticker}")
        return company

    def _request_json(self, url: str, params: dict[str, str] | None) -> dict[str, Any]:
        failures: list[str] = []
        host = urlsplit(url).hostname or url
        for attempt in range(self._MAX_ATTEMPTS):
            try:
                response = self._session.get(url, params=params, timeout=self._REQUEST_TIMEOUT)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise TypeError("response is not a JSON object")
                self._retry_count += attempt
                self._request_count += 1
                self._hosts_used.add(host)
                return payload
            except (requests.RequestException, ValueError, TypeError) as exc:
                failures.append(type(exc).__name__)
                self._reset_session()
                if attempt + 1 < self._MAX_ATTEMPTS:
                    time.sleep(0.25 * (2**attempt))
        raise USMarketDataError(f"{host} request failed ({', '.join(failures)})")

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "User-Agent": os.environ.get(
                "FASTAGENTFACTORY_SEC_USER_AGENT",
                self._DEFAULT_SEC_USER_AGENT,
            ).strip(),
        })
        return session

    def _reset_session(self) -> None:
        self._session.close()
        self._session = self._new_session()


def us_equity_ticker(value: str) -> str:
    ticker = str(value or "").strip().upper()
    if not _TICKER_RE.fullmatch(ticker):
        raise ValueError("ticker must be a valid U.S. equity symbol")
    return ticker.replace(".", "-")


def market_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if _MARKET_INDEX_RE.fullmatch(symbol):
        return symbol
    return us_equity_ticker(symbol)


def _screener_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": str(item.get("symbol") or ""),
        "name": str(item.get("shortName") or item.get("longName") or item.get("symbol") or ""),
        "exchange": str(item.get("fullExchangeName") or item.get("exchange") or ""),
        "price": _number(item.get("regularMarketPrice")),
        "change_pct": _number(item.get("regularMarketChangePercent")),
        "volume": _number(item.get("regularMarketVolume")),
        "market_cap_usd": _number(item.get("marketCap")),
    }


def _utc_timestamp(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value), UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _sequence_number(values: Any, index: int) -> float | int | None:
    return _number(values[index]) if isinstance(values, list) and index < len(values) else None


def _number(value: Any) -> float | int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 4)
