"""Private-company financial data ingestion via CSV or Excel upload.

Converts a structured spreadsheet into the repo's internal JSON schema so the
same agent pipeline can run on private / non-listed company data as on
Bloomberg PDFs or yfinance-fetched data.

Expected columns (case-insensitive, order does not matter):

    period          — required — "YYYY-FY" or "YYYY-QN", e.g. "2023-FY"
    revenue         — recommended (enables Revenue Agent)
    gross_profit
    operating_income
    net_income
    total_assets    — recommended (enables Balance Sheet + Liquidity Agents)
    total_liabilities
    current_assets
    current_liabilities
    equity
    ebitda
    interest_expense
    pretax_income
    income_tax
    depreciation
    total_debt
    long_term_debt
    short_term_debt
    cash_and_equivalents
    non_current_assets
    non_current_liabilities
    retained_earnings
    basic_eps
    diluted_eps
    cost_of_revenue

All numeric columns are optional but at least one must be present.
Values should be in a consistent unit (e.g. all in millions INR).

Requires:  pip install pandas openpyxl
"""
from __future__ import annotations

import io
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Known canonical field names — matches src/mapper.py + yfinance_ingestion.py
# ---------------------------------------------------------------------------

_CANONICAL_FIELDS: frozenset[str] = frozenset({
    "revenue", "gross_profit", "operating_income", "net_income",
    "total_assets", "total_liabilities", "current_assets", "current_liabilities",
    "equity", "ebitda", "interest_expense", "pretax_income", "income_tax",
    "depreciation", "total_debt", "long_term_debt", "short_term_debt",
    "cash_and_equivalents", "non_current_assets", "non_current_liabilities",
    "retained_earnings", "basic_eps", "diluted_eps", "cost_of_revenue",
})

_PERIOD_COL = "period"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase all column names and strip whitespace."""
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _validate_period(period: str) -> str:
    """Validate a period string is 'YYYY-FY' or 'YYYY-QN'."""
    import re
    p = str(period).strip()
    if not re.match(r"^\d{4}-(FY|Q[1-4])$", p, re.IGNORECASE):
        raise ValueError(
            f"Invalid period format: {p!r}. "
            "Expected 'YYYY-FY' or 'YYYY-QN' (e.g. '2023-FY', '2022-Q3')."
        )
    return p.upper()


def _df_to_time_series(
    df: pd.DataFrame,
) -> dict[str, list[dict[str, Any]]]:
    """Convert a DataFrame with a 'period' column into the time_series schema."""
    time_series: dict[str, list[dict[str, Any]]] = {}

    for field in _CANONICAL_FIELDS:
        if field not in df.columns:
            continue
        entries: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            val = row[field]
            period = row[_PERIOD_COL]
            if pd.isna(val):
                continue
            try:
                float_val = float(val)
            except (TypeError, ValueError):
                continue
            entries.append({"period": period, "value": float_val})

        if entries:
            time_series[field] = sorted(entries, key=lambda x: x["period"])

    return time_series


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_private_company_data(
    file_bytes: bytes,
    filename: str,
    company_name: str,
    currency: str = "INR",
) -> dict[str, Any]:
    """Parse a CSV or Excel file and return the repo's JSON schema.

    Args:
        file_bytes:   Raw bytes of the uploaded file.
        filename:     Original filename — used to detect CSV vs Excel.
        company_name: Company name entered by the user in the UI.
        currency:     Currency of the figures (default: INR).

    Returns:
        dict with keys ``"entity"`` and ``"time_series"`` — same schema as
        OCR / yfinance output.

    Raises:
        ValueError: on missing required columns, bad period formats, or
                    completely empty data.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in ("xlsx", "xls"):
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    elif ext == "csv":
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        # Try CSV as a fallback for unknown extensions
        try:
            df = pd.read_csv(io.BytesIO(file_bytes))
        except Exception:
            raise ValueError(
                f"Unsupported file type '{ext}'. Upload a .csv or .xlsx file."
            )

    df = _normalise_columns(df)

    # ── Validate required 'period' column ────────────────────────────────────
    if _PERIOD_COL not in df.columns:
        raise ValueError(
            f"Missing required column '{_PERIOD_COL}'. "
            "Your spreadsheet must have a 'period' column with values like '2023-FY'."
        )

    # Drop rows where period is blank
    df = df.dropna(subset=[_PERIOD_COL])
    if df.empty:
        raise ValueError("No data rows found after removing blank period values.")

    # Validate & normalise period strings
    try:
        df[_PERIOD_COL] = df[_PERIOD_COL].apply(_validate_period)
    except ValueError as exc:
        raise ValueError(f"Period column error: {exc}") from exc

    # Deduplicate periods (keep first)
    if df[_PERIOD_COL].duplicated().any():
        dups = df.loc[df[_PERIOD_COL].duplicated(), _PERIOD_COL].tolist()
        raise ValueError(f"Duplicate period values found: {dups}. Each period must appear once.")

    # ── Check at least one canonical field column exists ─────────────────────
    present_fields = _CANONICAL_FIELDS & set(df.columns)
    if not present_fields:
        canonical_list = ", ".join(sorted(_CANONICAL_FIELDS)[:8]) + ", …"
        raise ValueError(
            f"No recognised financial columns found. "
            f"Expected at least one of: {canonical_list}. "
            "Make sure column headers exactly match (e.g. 'revenue', 'total_assets')."
        )

    # ── Build time_series ─────────────────────────────────────────────────────
    time_series = _df_to_time_series(df)

    if not time_series:
        raise ValueError("All numeric columns contain only blank/NaN values.")

    # Ensure scaffold fields are always present (empty list when absent)
    for field in ("revenue", "net_income", "total_assets", "total_liabilities", "equity"):
        time_series.setdefault(field, [])

    company_safe = company_name.strip() or "Private Company"

    return {
        "entity": {
            "entity_id": company_safe,
            "source": "private_upload",
            "currency": currency.strip().upper() or "INR",
            "source_files": [filename],
        },
        "time_series": time_series,
    }


def get_template_csv() -> str:
    """Return a CSV template string that users can download as a starting point."""
    return (
        "period,revenue,gross_profit,operating_income,net_income,"
        "total_assets,total_liabilities,current_assets,current_liabilities,equity\n"
        "2020-FY,,,,,,,,,\n"
        "2021-FY,,,,,,,,,\n"
        "2022-FY,,,,,,,,,\n"
        "2023-FY,,,,,,,,,\n"
        "2024-FY,,,,,,,,,\n"
    )
