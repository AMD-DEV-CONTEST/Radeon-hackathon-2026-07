"""Data credibility verification module.

Runs source-specific and universal checks on ingested financial data and
produces a structured CredibilityReport with an overall confidence score.

Sources supported:
  - "bloomberg_pdf"  : checks PDF text for Bloomberg signatures + cross-ref
  - "ticker"         : dual-source cross-check (yfinance vs FMP) + freshness
  - "csv"            : accounting identity + internal consistency + plausibility

Usage:
    from src.data_verifier import run_verification
    report = run_verification(source="ticker", payload=payload,
                              ticker="INFY.NS", fmp_api_key="...")
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

STATUS_PASS = "pass"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"


@dataclass
class CredibilityCheck:
    name: str
    status: str          # pass / warn / fail / skip
    detail: str
    weight: int = 10     # max points this check can contribute to score


@dataclass
class CredibilityReport:
    source: str                              # bloomberg_pdf / ticker / csv
    entity: str
    checks: list[CredibilityCheck] = field(default_factory=list)

    @property
    def score(self) -> int:
        """0–100 weighted credibility score."""
        total_weight = sum(c.weight for c in self.checks if c.status != STATUS_SKIP)
        earned = sum(
            c.weight if c.status == STATUS_PASS else
            c.weight // 2 if c.status == STATUS_WARN else 0
            for c in self.checks
        )
        if total_weight == 0:
            return 50
        return round(earned / total_weight * 100)

    @property
    def confidence(self) -> str:
        s = self.score
        if s >= 80:
            return "HIGH"
        if s >= 55:
            return "MEDIUM"
        return "LOW"

    @property
    def confidence_colour(self) -> str:
        return {"HIGH": "#00FF88", "MEDIUM": "#FFB000", "LOW": "#FF4444"}[self.confidence]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_values(payload: dict[str, Any], field_name: str) -> list[float]:
    """Return all numeric values for a time_series field."""
    entries = (payload.get("time_series") or {}).get(field_name) or []
    return [float(e["value"]) for e in entries if isinstance(e, dict) and e.get("value") is not None]


def _ts_periods(payload: dict[str, Any], field_name: str) -> list[str]:
    entries = (payload.get("time_series") or {}).get(field_name) or []
    return [str(e["period"]) for e in entries if isinstance(e, dict) and e.get("period")]


def _latest_period(payload: dict[str, Any]) -> str | None:
    """Return the most recent period string across all time_series fields."""
    all_periods: set[str] = set()
    for entries in (payload.get("time_series") or {}).values():
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("period"):
                    all_periods.add(str(e["period"]))
    if not all_periods:
        return None
    return max(all_periods)


def _period_to_year(period: str) -> int | None:
    m = re.match(r"^(\d{4})", period)
    return int(m.group(1)) if m else None


def _available_fields(payload: dict[str, Any]) -> set[str]:
    ts = payload.get("time_series") or {}
    return {k for k, v in ts.items() if isinstance(v, list) and len(v) > 0}


# ---------------------------------------------------------------------------
# Universal checks (run for every source)
# ---------------------------------------------------------------------------

def _check_completeness(payload: dict[str, Any]) -> CredibilityCheck:
    """Score based on how many key financial fields are present."""
    key_fields = {
        "revenue", "gross_profit", "net_income", "operating_income",
        "total_assets", "total_liabilities", "equity",
        "current_assets", "current_liabilities", "ebitda",
    }
    avail = _available_fields(payload)
    present = key_fields & avail
    pct = len(present) / len(key_fields) * 100

    if pct >= 80:
        return CredibilityCheck("Field Completeness", STATUS_PASS,
                                f"{len(present)}/{len(key_fields)} key fields present ({pct:.0f}%)", weight=15)
    if pct >= 50:
        missing = sorted(key_fields - present)
        return CredibilityCheck("Field Completeness", STATUS_WARN,
                                f"{len(present)}/{len(key_fields)} fields ({pct:.0f}%). Missing: {', '.join(missing[:4])}"
                                + ("…" if len(missing) > 4 else ""), weight=15)
    return CredibilityCheck("Field Completeness", STATUS_FAIL,
                            f"Only {len(present)}/{len(key_fields)} key fields found ({pct:.0f}%). Data may be too sparse for reliable analysis.", weight=15)


def _check_temporal_coverage(payload: dict[str, Any]) -> CredibilityCheck:
    """At least 3 periods makes trend analysis meaningful."""
    rev_periods = _ts_periods(payload, "revenue") or _ts_periods(payload, "total_assets")
    n = len(set(rev_periods))
    if n >= 4:
        return CredibilityCheck("Temporal Coverage", STATUS_PASS, f"{n} periods available — good trend depth", weight=10)
    if n >= 2:
        return CredibilityCheck("Temporal Coverage", STATUS_WARN, f"Only {n} periods — CAGR / trend analysis will be limited", weight=10)
    return CredibilityCheck("Temporal Coverage", STATUS_FAIL, "Only 1 period found — trend analysis not possible", weight=10)


def _check_accounting_identity(payload: dict[str, Any]) -> CredibilityCheck:
    """Verify assets ≈ liabilities + equity per period."""
    assets = {e["period"]: e["value"] for e in (payload.get("time_series") or {}).get("total_assets", []) or [] if isinstance(e, dict)}
    liabs  = {e["period"]: e["value"] for e in (payload.get("time_series") or {}).get("total_liabilities", []) or [] if isinstance(e, dict)}
    equity = {e["period"]: e["value"] for e in (payload.get("time_series") or {}).get("equity", []) or [] if isinstance(e, dict)}

    common = set(assets) & set(liabs) & set(equity)
    if not common:
        return CredibilityCheck("Accounting Identity", STATUS_SKIP,
                                "Cannot check: assets, liabilities, and equity not all present", weight=20)

    mismatches = []
    for p in sorted(common):
        a, l, e = assets[p], liabs[p], equity[p]
        implied = l + e
        if abs(a) < 1:
            continue
        rel = abs(a - implied) / abs(a)
        if rel > 0.05:
            mismatches.append(f"{p}: {rel*100:.1f}% off")

    if not mismatches:
        return CredibilityCheck("Accounting Identity", STATUS_PASS,
                                "Assets = Liabilities + Equity verified across all periods (within 5%)", weight=20)
    if len(mismatches) <= len(common) // 2:
        return CredibilityCheck("Accounting Identity", STATUS_WARN,
                                f"Minor mismatch in {len(mismatches)} period(s): {', '.join(mismatches[:3])}. May indicate rounding.", weight=20)
    return CredibilityCheck("Accounting Identity", STATUS_FAIL,
                            f"Significant mismatch in {len(mismatches)} period(s): {', '.join(mismatches[:3])}. Check data source.", weight=20)


def _check_freshness(payload: dict[str, Any]) -> CredibilityCheck:
    """Flag data older than 18 months."""
    latest = _latest_period(payload)
    if not latest:
        return CredibilityCheck("Data Freshness", STATUS_SKIP, "Cannot determine latest period", weight=10)
    year = _period_to_year(latest)
    if not year:
        return CredibilityCheck("Data Freshness", STATUS_SKIP, f"Cannot parse period: {latest}", weight=10)
    current_year = datetime.now(timezone.utc).year
    age = current_year - year
    if age <= 1:
        return CredibilityCheck("Data Freshness", STATUS_PASS, f"Latest period: {latest} — current", weight=10)
    if age == 2:
        return CredibilityCheck("Data Freshness", STATUS_WARN, f"Latest period: {latest} — data is ~{age} years old", weight=10)
    return CredibilityCheck("Data Freshness", STATUS_FAIL, f"Latest period: {latest} — data is {age}+ years old (stale)", weight=10)


def _check_yoy_plausibility(payload: dict[str, Any]) -> CredibilityCheck:
    """Flag any field with >500% YoY change (likely a unit mismatch)."""
    ts = payload.get("time_series") or {}
    flagged = []
    for fname, entries in ts.items():
        if not isinstance(entries, list) or len(entries) < 2:
            continue
        vals = [e["value"] for e in sorted(entries, key=lambda x: x.get("period","")) if isinstance(e, dict) and e.get("value") is not None]
        for i in range(1, len(vals)):
            prev, curr = vals[i-1], vals[i]
            if abs(prev) < 1:
                continue
            change = abs((curr - prev) / prev)
            if change > 5.0:  # > 500%
                flagged.append(f"{fname}: {change*100:.0f}% jump")
                break
    if not flagged:
        return CredibilityCheck("YoY Plausibility", STATUS_PASS, "No implausibly large year-over-year swings detected", weight=10)
    return CredibilityCheck("YoY Plausibility", STATUS_WARN,
                            f"Large YoY changes detected (possible unit mismatch): {', '.join(flagged[:3])}. Verify units.", weight=10)


def _check_internal_consistency(payload: dict[str, Any]) -> CredibilityCheck:
    """Check field relationships: gross_profit ≤ revenue, current ≤ total, etc."""
    issues = []
    ts = payload.get("time_series") or {}

    def _map(fname):
        return {e["period"]: e["value"] for e in ts.get(fname, []) or [] if isinstance(e, dict)}

    rev  = _map("revenue")
    gp   = _map("gross_profit")
    ni   = _map("net_income")
    ca   = _map("current_assets")
    ta   = _map("total_assets")
    cl   = _map("current_liabilities")
    tl   = _map("total_liabilities")

    for p in set(rev) & set(gp):
        if abs(rev[p]) > 0 and gp[p] > rev[p] * 1.05:
            issues.append(f"gross_profit > revenue in {p}")

    for p in set(ca) & set(ta):
        if ta[p] > 0 and ca[p] > ta[p] * 1.05:
            issues.append(f"current_assets > total_assets in {p}")

    for p in set(cl) & set(tl):
        if tl[p] > 0 and cl[p] > tl[p] * 1.05:
            issues.append(f"current_liabilities > total_liabilities in {p}")

    if not (rev or gp or ca or ta):
        return CredibilityCheck("Internal Consistency", STATUS_SKIP, "Not enough fields to perform consistency checks", weight=15)
    if not issues:
        return CredibilityCheck("Internal Consistency", STATUS_PASS, "All field relationships are internally consistent", weight=15)
    return CredibilityCheck("Internal Consistency", STATUS_FAIL,
                            f"{len(issues)} inconsistency/ies found: {'; '.join(issues[:3])}", weight=15)


# ---------------------------------------------------------------------------
# Source-specific checks
# ---------------------------------------------------------------------------

def _check_bloomberg_signature(extracted_text: str) -> CredibilityCheck:
    """Look for Bloomberg-specific text markers in the extracted PDF text."""
    text_lower = extracted_text.lower()
    strong_markers = [
        "bloomberg finance l.p.",
        "bloomberg l.p.",
        "bloomberg terminal",
        "© bloomberg",
        "bloomberg data",
    ]
    soft_markers = [
        "bloomberg",
        "bbg",
        "bberg",
    ]
    found_strong = [m for m in strong_markers if m in text_lower]
    found_soft   = [m for m in soft_markers   if m in text_lower]

    if found_strong:
        return CredibilityCheck("Bloomberg Signature", STATUS_PASS,
                                f"Bloomberg copyright/legal notice found: '{found_strong[0]}'", weight=25)
    if found_soft:
        return CredibilityCheck("Bloomberg Signature", STATUS_WARN,
                                "Bloomberg name found but no legal notice / copyright text detected. "
                                "Could be a Bloomberg-referencing (not Bloomberg-sourced) document.", weight=25)
    return CredibilityCheck("Bloomberg Signature", STATUS_FAIL,
                            "No Bloomberg identifiers found in extracted text. "
                            "Document may not be a Bloomberg Financial Statement.", weight=25)


def _check_ticker_dual_source(
    payload: dict[str, Any],
    ticker: str,
    fmp_api_key: str,
) -> CredibilityCheck:
    """Cross-check yfinance revenue figures against FMP."""
    try:
        from src.supplemental_fetchers import fetch_missing_from_fmp
        fmp_data = fetch_missing_from_fmp(ticker, fmp_api_key, limit=5)
    except Exception as exc:
        return CredibilityCheck("Dual-Source Cross-Check", STATUS_SKIP,
                                f"FMP fetch failed (cannot cross-check): {exc}", weight=20)

    # Compare total_assets across common periods
    for field_name in ("total_assets", "revenue"):
        yf_entries = {e["period"]: e["value"] for e in (payload.get("time_series") or {}).get(field_name, []) or [] if isinstance(e, dict)}
        fmp_entries = {e["period"]: e["value"] for e in fmp_data.get(field_name, []) or [] if isinstance(e, dict)}
        common = set(yf_entries) & set(fmp_entries)
        if not common:
            continue

        diffs = []
        for p in common:
            yf_val, fmp_val = yf_entries[p], fmp_entries[p]
            if abs(yf_val) < 1:
                continue
            rel = abs(yf_val - fmp_val) / abs(yf_val)
            diffs.append(rel)

        if not diffs:
            continue
        avg_diff = float(np.mean(diffs)) * 100

        if avg_diff <= 5:
            return CredibilityCheck("Dual-Source Cross-Check", STATUS_PASS,
                                    f"yfinance vs FMP agreement: {avg_diff:.1f}% avg difference on '{field_name}' — ✅ consistent", weight=20)
        if avg_diff <= 15:
            return CredibilityCheck("Dual-Source Cross-Check", STATUS_WARN,
                                    f"yfinance vs FMP: {avg_diff:.1f}% avg difference on '{field_name}'. "
                                    "Minor discrepancy — may be due to currency/unit differences.", weight=20)
        return CredibilityCheck("Dual-Source Cross-Check", STATUS_FAIL,
                                f"yfinance vs FMP: {avg_diff:.1f}% avg difference on '{field_name}'. "
                                "Significant discrepancy — verify which source is correct.", weight=20)

    return CredibilityCheck("Dual-Source Cross-Check", STATUS_SKIP,
                            "No overlapping periods found between yfinance and FMP data", weight=20)


def _check_ticker_listing_status(ticker: str) -> CredibilityCheck:
    """Confirm ticker is actively traded (not delisted)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        mkt_cap = getattr(info, "market_cap", None)
        if mkt_cap and float(mkt_cap) > 0:
            return CredibilityCheck("Active Listing", STATUS_PASS,
                                    f"Ticker {ticker} is actively listed (market cap: {mkt_cap:,.0f})", weight=10)
        # Try history as backup
        hist = t.history(period="5d")
        if not hist.empty:
            return CredibilityCheck("Active Listing", STATUS_PASS,
                                    f"Ticker {ticker} has recent trading data — actively listed", weight=10)
        return CredibilityCheck("Active Listing", STATUS_WARN,
                                f"Could not confirm active trading for {ticker}. May be thinly traded or delisted.", weight=10)
    except Exception as exc:
        return CredibilityCheck("Active Listing", STATUS_SKIP, f"Could not verify listing status: {exc}", weight=10)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_verification(
    source: str,
    payload: dict[str, Any],
    extracted_text: str = "",
    ticker: str | None = None,
    fmp_api_key: str | None = None,
) -> CredibilityReport:
    """Run all applicable credibility checks and return a CredibilityReport.

    Args:
        source:         One of 'bloomberg_pdf', 'ticker', 'csv'.
        payload:        The ingested payload dict (entity + time_series).
        extracted_text: Raw OCR text from the PDF (bloomberg_pdf only).
        ticker:         Ticker symbol (ticker source; also used for cross-ref check).
        fmp_api_key:    Optional FMP key for dual-source verification (ticker source).

    Returns:
        A CredibilityReport with all checks and an overall score.
    """
    entity = str((payload.get("entity") or {}).get("entity_id") or "UNKNOWN")
    report = CredibilityReport(source=source, entity=entity)

    # ── Source-specific checks first ─────────────────────────────────────────
    if source == "bloomberg_pdf":
        if extracted_text:
            report.checks.append(_check_bloomberg_signature(extracted_text))
        else:
            report.checks.append(CredibilityCheck(
                "Bloomberg Signature", STATUS_SKIP,
                "No extracted text provided — cannot check PDF signature", weight=25
            ))

    elif source == "ticker":
        if ticker:
            report.checks.append(_check_ticker_listing_status(ticker))
        if ticker and fmp_api_key and fmp_api_key.strip():
            report.checks.append(_check_ticker_dual_source(payload, ticker, fmp_api_key))
        else:
            report.checks.append(CredibilityCheck(
                "Dual-Source Cross-Check", STATUS_SKIP,
                "Add FMP key in sidebar to enable yfinance ↔ FMP cross-verification", weight=20
            ))

    elif source == "csv":
        # For CSV, the internal consistency checks DO the heavy lifting
        # (no external source to compare against — it's private data)
        report.checks.append(CredibilityCheck(
            "Source Type", STATUS_WARN,
            "Private/manual upload — no external reference available for cross-verification. "
            "Internal consistency checks below are the primary credibility signal.", weight=5
        ))

    # ── Universal checks (all sources) ───────────────────────────────────────
    report.checks.append(_check_completeness(payload))
    report.checks.append(_check_temporal_coverage(payload))
    report.checks.append(_check_accounting_identity(payload))
    report.checks.append(_check_freshness(payload))
    report.checks.append(_check_yoy_plausibility(payload))
    report.checks.append(_check_internal_consistency(payload))

    return report
