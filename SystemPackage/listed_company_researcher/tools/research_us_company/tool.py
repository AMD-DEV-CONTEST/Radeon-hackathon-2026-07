from __future__ import annotations

from datetime import datetime
import math
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from agent_factory.market_data.us_equities import (
    US_EQUITY_SOURCE_NAME,
    USMarketDataClient,
    us_equity_ticker,
)


ALLOWED_SECTIONS = {"basic", "quote", "history", "financial"}


def run(arguments: dict, resources: dict) -> dict:
    del resources
    ticker = us_equity_ticker(arguments.get("ticker"))
    history_days = int(arguments.get("history_days", 250))
    if not 30 <= history_days <= 1000:
        raise ValueError("history_days must be between 30 and 1000")
    raw_sections = arguments.get("sections", ["basic", "quote", "history", "financial"])
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("sections must be a non-empty array")
    sections = {str(item) for item in raw_sections}
    unknown = sorted(sections - ALLOWED_SECTIONS)
    if unknown:
        raise ValueError(f"unsupported sections: {', '.join(unknown)}")

    result: dict[str, Any] = {
        "status": "success",
        "ticker": ticker,
        "name": ticker,
        "observed_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "source": US_EQUITY_SOURCE_NAME,
        "adjustment": "historical prices use Yahoo Finance adjusted close",
        "basic": [],
        "quote": {},
        "history_summary": {},
        "financial": [],
        "warnings": [],
        "message": "U.S. listed-company data retrieval completed.",
    }
    with USMarketDataClient() as market_data:
        try:
            quote = market_data.quote(ticker)
            result["name"] = str(quote["name"])
        except Exception as exc:
            return {
                **result,
                "status": "error",
                "warnings": [f"Security identity validation failed: {type(exc).__name__}: {exc}"],
                "message": "The ticker could not be confirmed as a U.S.-listed security.",
            }

        if "basic" in sections:
            result["basic"] = [
                {"item": "Ticker", "value": quote["ticker"]},
                {"item": "Company", "value": quote["name"]},
                {"item": "Exchange", "value": quote["exchange"]},
                {"item": "Instrument type", "value": quote["instrument_type"]},
                {"item": "Currency", "value": quote["currency"]},
                {"item": "Quote time", "value": quote["quote_time"]},
            ]
        if "quote" in sections:
            result["quote"] = quote
        if "history" in sections:
            try:
                result["history_summary"] = _history_summary(
                    market_data.history(ticker, count=history_days, adjustment="adjusted")
                )
            except Exception as exc:
                _warn(result, "Historical prices", exc)
        if "financial" in sections:
            try:
                result["financial"] = market_data.company_facts(ticker)
                if not result["financial"]:
                    raise ValueError("SEC company facts returned no supported concepts")
            except Exception as exc:
                _warn(result, "SEC company facts", exc)

    if result["warnings"]:
        has_data = any((result["basic"], result["quote"], result["history_summary"], result["financial"]))
        result["status"] = "partial" if has_data else "error"
        result["message"] = "Some company data is unavailable; constrain conclusions using warnings."
    return result


def _history_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(rows)
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if close.empty:
        raise ValueError("history contains no valid close prices")
    returns = close.pct_change().dropna()
    drawdown = close / close.cummax() - 1
    return {
        "start_date": str(frame.iloc[0]["date"]),
        "end_date": str(frame.iloc[-1]["date"]),
        "observations": int(len(close)),
        "first_close": _number(close.iloc[0]),
        "last_close": _number(close.iloc[-1]),
        "period_return_pct": _percent(close.iloc[-1] / close.iloc[0] - 1) if len(close) > 1 else None,
        "annualized_volatility_pct": _percent(returns.std() * math.sqrt(252)) if len(returns) > 1 else None,
        "max_drawdown_pct": _percent(drawdown.min()),
        "sma20": _number(close.tail(20).mean()) if len(close) >= 20 else None,
        "sma60": _number(close.tail(60).mean()) if len(close) >= 60 else None,
    }


def _warn(result: dict[str, Any], section: str, exc: Exception) -> None:
    result["warnings"].append(f"{section} unavailable: {type(exc).__name__}: {exc}")


def _number(value: Any) -> float | None:
    parsed = float(value)
    return round(parsed, 4) if math.isfinite(parsed) else None


def _percent(value: Any) -> float | None:
    return _number(float(value) * 100)
