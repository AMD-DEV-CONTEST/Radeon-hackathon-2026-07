"""yfinance ingestion — fetch financial data for listed companies by ticker.

Converts yfinance financial statements to the repo's internal JSON schema so
the same agent pipeline can run on ticker-fetched data as on Bloomberg PDFs.

Requires:  pip install yfinance
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Row-label → canonical field mappings
# (yfinance row index labels → our schema keys)
# ---------------------------------------------------------------------------

_INCOME_MAP: dict[str, str] = {
    "Total Revenue":                                    "revenue",
    "Net Revenue":                                      "revenue",
    "Operating Revenue":                                "revenue",
    "Gross Profit":                                     "gross_profit",
    "Operating Income":                                 "operating_income",
    "Ebit":                                             "operating_income",
    "Ebitda":                                           "ebitda",
    "Net Income":                                       "net_income",
    "Net Income Common Stockholders":                   "net_income",
    "Net Income Continuous Operations":                 "net_income",
    "Interest Expense":                                 "interest_expense",
    "Interest Expense Non Operating":                   "interest_expense",
    "Pretax Income":                                    "pretax_income",
    "Tax Provision":                                    "income_tax",
    "Basic Eps":                                        "basic_eps",
    "Diluted Eps":                                      "diluted_eps",
    "Reconciled Depreciation":                          "depreciation",
    "Depreciation And Amortization In Income Statement":"depreciation",
    "Cost Of Revenue":                                  "cost_of_revenue",
}

_BALANCE_MAP: dict[str, str] = {
    "Total Assets":                                         "total_assets",
    "Current Assets":                                       "current_assets",
    "Cash And Cash Equivalents":                            "cash_and_equivalents",
    "Cash Cash Equivalents And Short Term Investments":     "cash_and_equivalents",
    "Total Non Current Assets":                             "non_current_assets",
    "Net Ppe":                                              "non_current_assets",
    "Total Liabilities Net Minority Interest":              "total_liabilities",
    "Current Liabilities":                                  "current_liabilities",
    "Total Non Current Liabilities Net Minority Interest":  "non_current_liabilities",
    "Long Term Debt":                                       "long_term_debt",
    "Long Term Debt And Capital Lease Obligation":          "long_term_debt",
    "Current Debt":                                         "short_term_debt",
    "Current Debt And Capital Lease Obligation":            "short_term_debt",
    "Total Debt":                                           "total_debt",
    "Stockholders Equity":                                  "equity",
    "Common Stock Equity":                                  "equity",
    "Total Equity Gross Minority Interest":                 "equity",
    "Retained Earnings":                                    "retained_earnings",
}


def _to_period(ts: Any) -> str:
    """Convert a pandas Timestamp to 'YYYY-FY'."""
    return f"{pd.Timestamp(ts).year}-FY"


def _df_to_series(
    df: pd.DataFrame,
    col_map: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Convert a yfinance statement DataFrame (rows=labels, cols=dates) to
    the repo's time_series format. First match per canonical key wins."""
    result: dict[str, list[dict[str, Any]]] = {}
    for yf_label, canonical in col_map.items():
        if yf_label not in df.index:
            continue
        if canonical in result:   # first match wins; don't overwrite
            continue
        entries: list[dict[str, Any]] = []
        for ts, val in df.loc[yf_label].items():
            if pd.isna(val):
                continue
            entries.append({"period": _to_period(ts), "value": float(val)})
        if entries:
            result[canonical] = sorted(entries, key=lambda x: x["period"])
    return result


def fetch_by_ticker(ticker: str) -> dict[str, Any]:
    """Fetch annual financial data for *ticker* and return the repo's JSON schema.

    Args:
        ticker: Yahoo Finance ticker symbol, e.g. ``"HDFCBANK.NS"``, ``"AAPL"``.

    Returns:
        dict with keys ``"entity"`` and ``"time_series"`` — same schema as OCR output.

    Raises:
        ValueError: if yfinance returns no data for the ticker.
    """
    t = yf.Ticker(ticker)

    info: dict[str, Any] = {}
    try:
        info = t.info or {}
    except Exception:
        pass

    company_name: str = (
        info.get("longName") or info.get("shortName") or ticker.upper()
    )
    currency: str = info.get("currency") or "USD"

    financials = t.financials    # income statement — rows=labels, cols=timestamps
    balance    = t.balance_sheet

    if (financials is None or financials.empty) and (balance is None or balance.empty):
        raise ValueError(
            f"No financial data returned by yfinance for ticker '{ticker}'. "
            "Check that the symbol is valid (e.g. 'HDFCBANK.NS', 'RELIANCE.NS', 'AAPL')."
        )

    time_series: dict[str, list[dict[str, Any]]] = {}

    if financials is not None and not financials.empty:
        time_series.update(_df_to_series(financials, _INCOME_MAP))

    if balance is not None and not balance.empty:
        for k, v in _df_to_series(balance, _BALANCE_MAP).items():
            if k not in time_series:
                time_series[k] = v

    # Ensure required scaffold fields are always present (empty list when absent).
    for field in ("revenue", "net_income", "total_assets", "total_liabilities", "total_debt", "equity"):
        time_series.setdefault(field, [])

    return {
        "entity": {
            "entity_id": company_name,
            "source":    "yfinance",
            "currency":  currency,
            "source_files": [ticker],
        },
        "time_series": time_series,
    }
