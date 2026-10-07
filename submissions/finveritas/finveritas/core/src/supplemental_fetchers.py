"""Supplemental data fetchers for missing balance-sheet fields.

When yfinance returns incomplete data (e.g. missing current_assets /
current_liabilities for Indian banks), these fetchers attempt to retrieve
the missing fields from alternative free-tier APIs.

Fallback priority:
  1. Financial Modeling Prep (FMP)  — 250 req/day free
  2. Alpha Vantage                  — 25 req/day free
  3. Manual entry                   — always available (handled in app.py)

Both fetchers return data in the repo's internal time_series format:
  {canonical_field: [{"period": "YYYY-FY", "value": float}, ...]}

Only the fields listed in SUPPLEMENTAL_FIELDS are fetched and returned —
other fields are ignored to avoid overwriting data already present.
"""
from __future__ import annotations

import re
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Fields we care about supplementing (the ones yfinance commonly omits)
# ---------------------------------------------------------------------------

SUPPLEMENTAL_FIELDS: frozenset[str] = frozenset({
    "current_assets",
    "current_liabilities",
    "total_assets",
    "total_liabilities",
    "equity",
    "total_debt",
    "long_term_debt",
    "short_term_debt",
    "cash_and_equivalents",
    "retained_earnings",
})

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _to_period(date_str: str) -> str | None:
    """Convert 'YYYY-MM-DD' or 'YYYY' → 'YYYY-FY'. Returns None if unparseable."""
    m = re.match(r"^(\d{4})", str(date_str).strip())
    return f"{m.group(1)}-FY" if m else None


def _make_series(value_map: dict[str, float]) -> list[dict[str, Any]]:
    """Convert {period: value} → sorted list of {period, value} dicts."""
    return sorted(
        [{"period": p, "value": v} for p, v in value_map.items()],
        key=lambda x: x["period"],
    )


# ---------------------------------------------------------------------------
# Financial Modeling Prep (FMP)
# ---------------------------------------------------------------------------

_FMP_FIELD_MAP: dict[str, str] = {
    "currentAssets":              "current_assets",
    "totalCurrentAssets":         "current_assets",
    "currentLiabilities":         "current_liabilities",
    "totalCurrentLiabilities":    "current_liabilities",
    "totalAssets":                "total_assets",
    "totalLiabilities":           "total_liabilities",
    "totalLiabilitiesAndEquity":  "total_liabilities",   # fallback
    "totalStockholdersEquity":    "equity",
    "totalEquity":                "equity",
    "netDebt":                    "total_debt",
    "totalDebt":                  "total_debt",
    "longTermDebt":               "long_term_debt",
    "shortTermDebt":              "short_term_debt",
    "cashAndShortTermInvestments":"cash_and_equivalents",
    "cashAndCashEquivalents":     "cash_and_equivalents",
    "retainedEarnings":           "retained_earnings",
}

_FMP_BASE = "https://financialmodelingprep.com/api/v3"


def fetch_missing_from_fmp(
    ticker: str,
    fmp_api_key: str,
    limit: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch annual balance-sheet data from FMP for *ticker*.

    Args:
        ticker:      Yahoo-style ticker, e.g. ``"YESBANK.NS"``, ``"AAPL"``.
        fmp_api_key: FMP API key (free tier at financialmodelingprep.com).
        limit:       Number of annual periods to fetch (default 5).

    Returns:
        Dict mapping canonical field names → time_series lists.
        Only fields in SUPPLEMENTAL_FIELDS are included.

    Raises:
        ValueError: if the API returns an error or no data.
        requests.HTTPError: on HTTP-level failures.
    """
    url = f"{_FMP_BASE}/balance-sheet-statement/{ticker}"
    params = {"period": "annual", "limit": limit, "apikey": fmp_api_key}

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict) and "Error Message" in data:
        raise ValueError(f"FMP error: {data['Error Message']}")
    if not isinstance(data, list) or not data:
        raise ValueError(
            f"FMP returned no balance-sheet data for ticker '{ticker}'. "
            "Check that the ticker is valid (e.g. 'YESBANK.NS', 'AAPL')."
        )

    # Accumulate: canonical_field → {period: value}
    result: dict[str, dict[str, float]] = {}

    for statement in data:
        date_str = statement.get("date") or statement.get("fillingDate") or ""
        period = _to_period(date_str)
        if not period:
            continue

        for fmp_key, canonical in _FMP_FIELD_MAP.items():
            if canonical not in SUPPLEMENTAL_FIELDS:
                continue
            raw = statement.get(fmp_key)
            if raw is None:
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            result.setdefault(canonical, {})[period] = val

    if not result:
        raise ValueError(
            f"FMP returned a response for '{ticker}' but no recognisable "
            "balance-sheet fields could be extracted."
        )

    return {field: _make_series(pv) for field, pv in result.items()}


# ---------------------------------------------------------------------------
# Alpha Vantage
# ---------------------------------------------------------------------------

_AV_FIELD_MAP: dict[str, str] = {
    "totalCurrentAssets":         "current_assets",
    "totalCurrentLiabilities":    "current_liabilities",
    "totalAssets":                "total_assets",
    "totalLiabilities":           "total_liabilities",
    "totalShareholderEquity":     "equity",
    "longTermDebt":               "long_term_debt",
    "shortLongTermDebtTotal":     "total_debt",
    "cashAndCashEquivalentsAtCarryingValue": "cash_and_equivalents",
    "retainedEarnings":           "retained_earnings",
}

_AV_BASE = "https://www.alphavantage.co/query"


def fetch_missing_from_alpha_vantage(
    ticker: str,
    av_api_key: str,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch annual balance-sheet data from Alpha Vantage for *ticker*.

    Args:
        ticker:     Yahoo-style ticker, e.g. ``"YESBANK.NS"``, ``"AAPL"``.
        av_api_key: Alpha Vantage API key (free tier at alphavantage.co).

    Returns:
        Dict mapping canonical field names → time_series lists.
        Only fields in SUPPLEMENTAL_FIELDS are included.

    Raises:
        ValueError: if the API returns an error or no data.
        requests.HTTPError: on HTTP-level failures.
    """
    params = {
        "function": "BALANCE_SHEET",
        "symbol": ticker,
        "apikey": av_api_key,
    }
    resp = requests.get(_AV_BASE, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "Note" in data:
        raise ValueError(
            "Alpha Vantage rate limit reached (25 req/day on free tier). "
            "Try again tomorrow or use FMP instead."
        )
    if "Information" in data:
        raise ValueError(f"Alpha Vantage: {data['Information']}")
    if "Error Message" in data:
        raise ValueError(f"Alpha Vantage error: {data['Error Message']}")

    annual_reports = data.get("annualReports") or []
    if not annual_reports:
        raise ValueError(
            f"Alpha Vantage returned no annual balance-sheet data for '{ticker}'."
        )

    result: dict[str, dict[str, float]] = {}

    for report in annual_reports:
        date_str = report.get("fiscalDateEnding") or ""
        period = _to_period(date_str)
        if not period:
            continue

        for av_key, canonical in _AV_FIELD_MAP.items():
            if canonical not in SUPPLEMENTAL_FIELDS:
                continue
            raw = report.get(av_key)
            if raw is None or str(raw).strip().lower() in ("none", "", "n/a"):
                continue
            try:
                val = float(str(raw).replace(",", ""))
            except (TypeError, ValueError):
                continue
            result.setdefault(canonical, {})[period] = val

    if not result:
        raise ValueError(
            f"Alpha Vantage returned data for '{ticker}' but no recognisable "
            "balance-sheet fields could be extracted."
        )

    return {field: _make_series(pv) for field, pv in result.items()}


# ---------------------------------------------------------------------------
# Orchestrator — tries both sources, returns best combined result
# ---------------------------------------------------------------------------

def auto_fetch_missing_fields(
    ticker: str,
    missing_fields: set[str],
    fmp_api_key: str | None = None,
    av_api_key: str | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[str], list[str]]:
    """Try FMP then Alpha Vantage to resolve *missing_fields* for *ticker*.

    Args:
        ticker:        Ticker symbol.
        missing_fields: Set of canonical field names that need to be resolved.
        fmp_api_key:   Optional FMP key.
        av_api_key:    Optional Alpha Vantage key.

    Returns:
        (resolved_data, resolved_fields, errors)
        - resolved_data: dict of field → time_series for fields that were found
        - resolved_fields: list of canonical fields successfully fetched
        - errors: list of human-readable error messages from each failed attempt
    """
    resolved: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []

    # --- Try FMP ---
    if fmp_api_key and fmp_api_key.strip():
        try:
            fmp_data = fetch_missing_from_fmp(ticker, fmp_api_key.strip())
            for field, series in fmp_data.items():
                if field in missing_fields and field not in resolved:
                    resolved[field] = series
        except Exception as exc:
            errors.append(f"FMP: {exc}")

    # --- Try Alpha Vantage for anything still missing ---
    still_missing = missing_fields - set(resolved)
    if still_missing and av_api_key and av_api_key.strip():
        try:
            av_data = fetch_missing_from_alpha_vantage(ticker, av_api_key.strip())
            for field, series in av_data.items():
                if field in still_missing and field not in resolved:
                    resolved[field] = series
        except Exception as exc:
            errors.append(f"Alpha Vantage: {exc}")

    resolved_fields = [f for f in missing_fields if f in resolved]
    return resolved, resolved_fields, errors
