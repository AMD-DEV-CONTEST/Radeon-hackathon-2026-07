from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from agent_factory.market_data.us_equities import (
    US_EQUITY_SOURCE_NAME,
    USMarketDataClient,
    USMarketDataError,
)


INDEXES = {
    "S&P 500": "^GSPC",
    "Dow Jones Industrial Average": "^DJI",
    "Nasdaq Composite": "^IXIC",
    "Russell 2000": "^RUT",
}


def run(arguments: dict, resources: dict) -> dict:
    del resources
    top_n = int(arguments.get("top_n", 10))
    if not 1 <= top_n <= 20:
        raise ValueError("top_n must be between 1 and 20")
    observed_at = datetime.now(ZoneInfo("America/New_York")).isoformat()
    warnings: list[str] = []
    indexes: list[dict[str, Any]] = []

    with USMarketDataClient() as market_data:
        for name, ticker in INDEXES.items():
            try:
                indexes.append({"index_name": name, **market_data.quote(ticker)})
            except USMarketDataError as exc:
                warnings.append(f"{name} quote unavailable: {exc}")
        top_gainers = _screener(market_data, "day_gainers", top_n, warnings)
        top_losers = _screener(market_data, "day_losers", top_n, warnings)
        most_active = _screener(market_data, "most_actives", top_n, warnings)
        status = "success" if not warnings else "partial" if indexes else "error"
        return {
            "status": status,
            "observed_at": observed_at,
            "source": US_EQUITY_SOURCE_NAME,
            "indexes": indexes,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "most_active": most_active,
            "warnings": warnings,
            "provider_diagnostics": market_data.diagnostics(),
            "message": (
                "U.S. equity market snapshot completed."
                if status == "success"
                else "The U.S. equity snapshot is incomplete; preserve the warnings in any report."
            ),
        }


def _screener(
    market_data: USMarketDataClient,
    screen_id: str,
    top_n: int,
    warnings: list[str],
) -> list[dict[str, Any]]:
    try:
        return market_data.screener(screen_id, count=top_n)
    except USMarketDataError as exc:
        warnings.append(f"{screen_id} screener unavailable: {exc}")
        return []
