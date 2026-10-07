"""
Explainable, entity-first financial background check prototype.

Overview
--------
This script implements a minimal, auditable multi-agent architecture for
financial background checks using only transparent, rule-based logic and
simple time-series statistics (no black-box ML, no autonomous decisions).

Agents
------
1. RevenueStabilityAgent
   - Consumes monthly revenue time series (pandas Series/DataFrame).
   - Computes trend, volatility, and persistence of growth/decline.

2. CashFlowAgent
   - Consumes monthly cash flow time series.
   - Focuses on sign (positive/negative), volatility, and persistence of
     negative cash flow.

3. LiabilityDebtAgent
   - Consumes monthly debt and equity time series.
   - Analyzes debt and equity trends and leverage (Debt/Equity).

4. CrossReferenceAgent
   - Consumes ONLY other agent outputs (no raw financial data).
   - Identifies consistencies and conflicts across agents.
   - Produces a *risk summary*, not an approve/reject verdict.

Rule Layer
----------
A simple, explicit rule-based layer examines agent and cross-reference
outputs and raises manual-review flags (guardrails only). It does NOT
produce approve/reject decisions.

Key Properties
--------------
- No forecasting, no neural networks, no external APIs.
- Time-series driven where relevant (monthly data).
- All computations are explicit and traceable.
- Final output includes:
  * Per-agent structured outputs
  * Cross-reference risk summary
  * Explicitly triggered rules (if any)
  * A human-readable explanation of how the result was reached

Dependencies
------------
- Python 3.10+
- pandas
- numpy
- openpyxl (for reading Excel input)

Usage
-----
1. Install pandas (if needed):
   pip install pandas

2. Run the script:
   python financial_background_check.py

This will execute the full pipeline on mock data and print a structured,
human-readable explainability report to stdout.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TimeSeriesMetrics:
    """Simple, interpretable time-series statistics for one numeric series."""
    trend_direction: str           # "increasing" | "decreasing" | "flat"
    trend_slope_per_step: float    # linear slope per time step
    volatility: float              # standard deviation of series values
    volatility_label: str          # "low" | "medium" | "high"
    persistence_description: str   # human-readable description


@dataclass
class AgentOutput:
    """Standard structure for all agent outputs."""
    agent_name: str
    entity_id: str
    inputs_summary: Dict[str, Any]
    metrics: Dict[str, TimeSeriesMetrics]
    overall_assessment: str
    notes: List[str]


@dataclass
class CrossReferenceOutput:
    """Output of the Cross-Reference Agent."""
    agent_name: str
    entity_id: str
    consistencies: List[str]
    conflicts: List[str]
    risk_indicators: List[str]
    overall_summary: str


@dataclass
class RuleResult:
    """Result of evaluating a single guardrail rule."""
    rule_id: str
    description: str
    triggered: bool
    reason: Optional[str]


# ---------------------------------------------------------------------------
# Generic time-series analysis helpers (no ML, only transparent statistics)
# ---------------------------------------------------------------------------

def compute_trend_and_volatility(
    series: pd.Series,
    volatility_thresholds: Tuple[float, float] = (0.05, 0.15),
) -> TimeSeriesMetrics:
    """
    Compute simple, explainable metrics on a 1D time series.

    - Trend: sign of linear slope (using np.polyfit on the index as x).
    - Volatility: standard deviation and label based on fixed thresholds.
    - Persistence: fraction of positive vs negative month-over-month changes.
    """
    if series.empty:
        return TimeSeriesMetrics(
            trend_direction="unknown",
            trend_slope_per_step=0.0,
            volatility=0.0,
            volatility_label="unknown",
            persistence_description="no data",
        )

    # Normalize index to 0..n-1 for slope calculation
    x = np.arange(len(series), dtype=float)
    y = series.values.astype(float)

    # Simple linear regression (degree 1) for slope
    slope, intercept = np.polyfit(x, y, 1)

    if slope > 0:
        trend_direction = "increasing"
    elif slope < 0:
        trend_direction = "decreasing"
    else:
        trend_direction = "flat"

    # Volatility: standard deviation of absolute values relative to mean
    std_dev = float(np.std(y))
    volatility = std_dev

    # Volatility labeling using coefficient of variation when mean != 0
    mean_val = float(np.mean(y))
    if mean_val != 0:
        cov = abs(std_dev / mean_val)
    else:
        cov = 0.0

    low_thresh, high_thresh = volatility_thresholds
    if cov < low_thresh:
        vol_label = "low"
    elif cov < high_thresh:
        vol_label = "medium"
    else:
        vol_label = "high"

    # Persistence: look at month-over-month changes
    diffs = np.diff(y)
    if len(diffs) == 0:
        persistence = "insufficient length for persistence analysis"
    else:
        positive_share = np.mean(diffs > 0)
        negative_share = np.mean(diffs < 0)
        if positive_share >= 0.7:
            persistence = "consistently increasing (>=70% of periods up)"
        elif negative_share >= 0.7:
            persistence = "consistently decreasing (>=70% of periods down)"
        else:
            persistence = "mixed pattern (no dominant direction)"

    return TimeSeriesMetrics(
        trend_direction=trend_direction,
        trend_slope_per_step=float(slope),
        volatility=volatility,
        volatility_label=vol_label,
        persistence_description=persistence,
    )


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class RevenueStabilityAgent:
    """Analyzes stability and trend of revenue over time."""

    def __init__(self) -> None:
        self.name = "RevenueStabilityAgent"

    def run(self, entity_id: str, revenue_series: pd.Series) -> AgentOutput:
        metrics = compute_trend_and_volatility(revenue_series)

        notes = []
        notes.append(
            f"Revenue trend is {metrics.trend_direction} "
            f"with slope {metrics.trend_slope_per_step:.2f} per period."
        )
        notes.append(
            f"Revenue volatility is {metrics.volatility:.2f} "
            f"labeled as {metrics.volatility_label}."
        )
        notes.append(f"Persistence assessment: {metrics.persistence_description}.")

        overall_assessment = (
            "Revenue appears stable with modest variability."
            if metrics.volatility_label in ("low", "medium")
            else "Revenue is volatile and may warrant closer inspection."
        )

        return AgentOutput(
            agent_name=self.name,
            entity_id=entity_id,
            inputs_summary={
                "periods": len(revenue_series),
                "start_date": str(revenue_series.index.min()),
                "end_date": str(revenue_series.index.max()),
                "min_revenue": float(revenue_series.min()),
                "max_revenue": float(revenue_series.max()),
            },
            metrics={"revenue": metrics},
            overall_assessment=overall_assessment,
            notes=notes,
        )


class CashFlowAgent:
    """Analyzes stability and sign behavior of cash flow over time."""

    def __init__(self) -> None:
        self.name = "CashFlowAgent"

    def run(self, entity_id: str, cash_flow_series: pd.Series) -> AgentOutput:
        metrics = compute_trend_and_volatility(cash_flow_series)

        # Additional cash-flow-specific stats
        cf_values = cash_flow_series.values.astype(float)
        negative_share = float(np.mean(cf_values < 0))
        avg_cf = float(np.mean(cf_values))
        print(f"cf_values")
        notes = []
        notes.append(
            f"Cash flow trend is {metrics.trend_direction} "
            f"with slope {metrics.trend_slope_per_step:.2f} per period."
        )
        notes.append(
            f"Cash flow volatility is {metrics.volatility:.2f} "
            f"labeled as {metrics.volatility_label}."
        )
        notes.append(
            f"Average monthly cash flow is {avg_cf:.2f}; "
            f"{negative_share*100:.1f}% of months have negative cash flow."
        )
        notes.append(f"Persistence assessment: {metrics.persistence_description}.")

        if negative_share > 0.5:
            overall = (
                "Cash flow is frequently negative and may indicate "
                "liquidity pressure."
            )
        else:
            overall = "Cash flow is mostly non-negative with manageable variability."

        return AgentOutput(
            agent_name=self.name,
            entity_id=entity_id,
            inputs_summary={
                "periods": len(cash_flow_series),
                "start_date": str(cash_flow_series.index.min()),
                "end_date": str(cash_flow_series.index.max()),
                "min_cash_flow": float(cash_flow_series.min()),
                "max_cash_flow": float(cash_flow_series.max()),
                "negative_month_share": negative_share,
                "average_cash_flow": avg_cf,
            },
            metrics={"cash_flow": metrics},
            overall_assessment=overall,
            notes=notes,
        )


class LiabilityDebtAgent:
    """Analyzes debt, equity, and leverage (debt/equity) over time."""

    def __init__(self) -> None:
        self.name = "LiabilityDebtAgent"

    def run(
        self,
        entity_id: str,
        debt_series: pd.Series,
        equity_series: pd.Series,
    ) -> AgentOutput:
        debt_metrics = compute_trend_and_volatility(debt_series)
        equity_metrics = compute_trend_and_volatility(equity_series)

        # Compute leverage safely where equity != 0
        equity_safe = equity_series.replace(0, np.nan)
        leverage = debt_series / equity_safe
        latest_leverage = float(leverage.iloc[-1]) if not leverage.empty else float("nan")

        # Simple leverage trend: reuse generic helper if we have enough data
        leverage_metrics = (
            compute_trend_and_volatility(leverage.dropna())
            if leverage.notna().sum() >= 3
            else TimeSeriesMetrics(
                trend_direction="unknown",
                trend_slope_per_step=0.0,
                volatility=0.0,
                volatility_label="unknown",
                persistence_description="insufficient leverage data",
            )
        )

        notes = []
        notes.append(
            f"Debt trend is {debt_metrics.trend_direction} "
            f"with slope {debt_metrics.trend_slope_per_step:.2f}."
        )
        notes.append(
            f"Equity trend is {equity_metrics.trend_direction} "
            f"with slope {equity_metrics.trend_slope_per_step:.2f}."
        )
        notes.append(
            f"Latest debt/equity ratio is {latest_leverage:.2f} "
            "(NaN indicates zero or missing equity)."
        )
        notes.append(
            f"Leverage trend is {leverage_metrics.trend_direction} "
            f"with slope {leverage_metrics.trend_slope_per_step:.2f}."
        )

        if latest_leverage > 3.0:
            overall = (
                "Leverage is elevated (debt/equity > 3.0), which may increase "
                "financial risk."
            )
        else:
            overall = "Leverage appears within a moderate range."

        return AgentOutput(
            agent_name=self.name,
            entity_id=entity_id,
            inputs_summary={
                "periods": len(debt_series),
                "start_date": str(debt_series.index.min()),
                "end_date": str(debt_series.index.max()),
                "latest_debt": float(debt_series.iloc[-1]),
                "latest_equity": float(equity_series.iloc[-1]),
                "latest_debt_to_equity": latest_leverage,
            },
            metrics={
                "debt": debt_metrics,
                "equity": equity_metrics,
                "leverage": leverage_metrics,
            },
            overall_assessment=overall,
            notes=notes,
        )


class CrossReferenceAgent:
    """
    Consumes only other agent outputs and identifies consistencies and conflicts.

    It does not access raw financial data and does not make approve/reject
    decisions. It only produces a risk-oriented narrative and indicators.
    """

    def __init__(self) -> None:
        self.name = "CrossReferenceAgent"

    def run(
        self,
        entity_id: str,
        revenue_output: AgentOutput,
        cashflow_output: AgentOutput,
        debt_output: AgentOutput,
    ) -> CrossReferenceOutput:
        consistencies: List[str] = []
        conflicts: List[str] = []
        risk_indicators: List[str] = []

        rev_metrics = revenue_output.metrics["revenue"]
        cf_metrics = cashflow_output.metrics["cash_flow"]
        lev_metrics = debt_output.metrics["leverage"]

        # Example consistency: revenue increasing & cash flow improving
        if (
            rev_metrics.trend_direction == "increasing"
            and cf_metrics.trend_direction in ("increasing", "flat")
        ):
            consistencies.append(
                "Revenue is increasing and cash flow is not deteriorating."
            )

        # Example conflict: revenue increasing but cash flow decreasing or often negative
        negative_cf_share = float(cashflow_output.inputs_summary["negative_month_share"])
        if (
            rev_metrics.trend_direction == "increasing"
            and cf_metrics.trend_direction == "decreasing"
        ):
            conflicts.append(
                "Revenue is increasing while cash flow trend is decreasing."
            )
            risk_indicators.append(
                "Potential revenue quality issue: growth not translating into cash."
            )
        if negative_cf_share > 0.5 and rev_metrics.trend_direction == "increasing":
            conflicts.append(
                "More than half of months show negative cash flow despite "
                "increasing revenue."
            )
            risk_indicators.append(
                "Sustainability risk: operations may rely on external funding."
            )

        # Example conflict: high or rising leverage with unstable cash flow
        latest_leverage = float(
            debt_output.inputs_summary.get("latest_debt_to_equity", float("nan"))
        )
        if latest_leverage > 3.0:
            risk_indicators.append(
                "High leverage (debt/equity > 3.0) may amplify downside risk."
            )

        if (
            lev_metrics.trend_direction == "increasing"
            and cf_metrics.trend_direction in ("decreasing", "flat")
        ):
            conflicts.append(
                "Leverage is increasing while cash flow is not clearly improving."
            )
            risk_indicators.append(
                "Increasing leverage without clear cash flow support."
            )

        if not conflicts and not risk_indicators:
            overall = (
                "No major cross-agent conflicts detected. Metrics are broadly "
                "self-consistent, though this is not a risk-free guarantee."
            )
        else:
            overall_parts = []
            if conflicts:
                overall_parts.append(
                    f"{len(conflicts)} conflict(s) identified across agents."
                )
            if risk_indicators:
                overall_parts.append(
                    f"{len(risk_indicators)} risk indicator(s) highlighted."
                )
            overall = " ".join(overall_parts)

        return CrossReferenceOutput(
            agent_name=self.name,
            entity_id=entity_id,
            consistencies=consistencies,
            conflicts=conflicts,
            risk_indicators=risk_indicators,
            overall_summary=overall,
        )


# ---------------------------------------------------------------------------
# Rule-based review layer (guardrails only, no decisions)
# ---------------------------------------------------------------------------

def apply_review_rules(
    entity_id: str,
    revenue_output: AgentOutput,
    cashflow_output: AgentOutput,
    debt_output: AgentOutput,
    crossref_output: CrossReferenceOutput,
) -> List[RuleResult]:
    """
    Evaluate a small set of explicit rules that ONLY trigger manual review flags.

    These rules do not approve or reject entities; they just highlight patterns
    that should receive human attention.
    """
    results: List[RuleResult] = []

    rev_metrics = revenue_output.metrics["revenue"]
    cf_metrics = cashflow_output.metrics["cash_flow"]
    lev_metrics = debt_output.metrics["leverage"]
    latest_leverage = float(
        debt_output.inputs_summary.get("latest_debt_to_equity", float("nan"))
    )
    negative_cf_share = float(cashflow_output.inputs_summary["negative_month_share"])

    # Rule 1: High revenue volatility
    rule_id = "R1_HIGH_REVENUE_VOLATILITY"
    desc = (
        "Trigger manual review when revenue volatility label is 'high', "
        "as revenue may not be stable."
    )
    triggered = rev_metrics.volatility_label == "high"
    reason = (
        f"Revenue volatility labeled as {rev_metrics.volatility_label}."
        if triggered
        else None
    )
    results.append(
        RuleResult(rule_id=rule_id, description=desc, triggered=triggered, reason=reason)
    )

    # Rule 2: Persistent negative cash flow
    rule_id = "R2_PERSISTENT_NEGATIVE_CASH_FLOW"
    desc = (
        "Trigger manual review when more than 50% of months have negative "
        "operating cash flow."
    )
    triggered = negative_cf_share > 0.5
    reason = (
        f"{negative_cf_share*100:.1f}% of months have negative cash flow."
        if triggered
        else None
    )
    results.append(
        RuleResult(rule_id=rule_id, description=desc, triggered=triggered, reason=reason)
    )

    # Rule 3: High or rising leverage
    rule_id = "R3_ELEVATED_OR_INCREASING_LEVERAGE"
    desc = (
        "Trigger manual review when latest debt/equity ratio exceeds 3.0 or "
        "leverage trend is increasing."
    )
    triggered = latest_leverage > 3.0 or lev_metrics.trend_direction == "increasing"
    if triggered:
        reason_parts = []
        if latest_leverage > 3.0:
            reason_parts.append(
                f"Latest debt/equity ratio is {latest_leverage:.2f} (> 3.0)."
            )
        if lev_metrics.trend_direction == "increasing":
            reason_parts.append("Leverage trend is increasing.")
        reason = " ".join(reason_parts)
    else:
        reason = None
    results.append(
        RuleResult(rule_id=rule_id, description=desc, triggered=triggered, reason=reason)
    )

    # Rule 4: Any cross-agent conflicts
    rule_id = "R4_CROSS_AGENT_CONFLICTS"
    desc = (
        "Trigger manual review when cross-reference agent reports any conflicts "
        "between revenue, cash flow, and leverage behavior."
    )
    triggered = len(crossref_output.conflicts) > 0
    reason = (
        f"{len(crossref_output.conflicts)} conflict(s) reported by cross-reference."
        if triggered
        else None
    )
    results.append(
        RuleResult(rule_id=rule_id, description=desc, triggered=triggered, reason=reason)
    )

    return results


# ---------------------------------------------------------------------------
# Data loading from Excel
# ---------------------------------------------------------------------------

def load_timeseries_from_excel(
    path: str,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Load financial time series from the Screener.in-style Data Sheet.

    This implementation is tailored to the layout of ``HCL Technologies.xlsx``:
    - Uses the ``Data Sheet`` worksheet.
    - Extracts annual ``Report Date`` rows for both PROFIT & LOSS and
      BALANCE SHEET sections (expected 2016–2025).
    - Uses ``Sales`` as a revenue series.
    - Uses ``Net profit`` as a simple proxy for cash-flow-like earnings.
    - Uses ``Borrowings`` as debt and ``Equity Share Capital + Reserves``
      as equity.

    All series are returned as pandas Series indexed by the corresponding
    report dates. This keeps the rest of the pipeline and static rules
    unchanged while grounding them on real, annual time-series data from
    the workbook.
    """
    df = pd.read_excel(path, sheet_name="Data Sheet", header=None)

    # Find PROFIT & LOSS and BALANCE SHEET date header rows
    report_rows = [idx for idx in df.index if df.iloc[idx, 0] == "Report Date"]
    if len(report_rows) < 2:
        raise ValueError(
            "Expected at least two 'Report Date' rows in Data Sheet for "
            "PROFIT & LOSS and BALANCE SHEET sections."
        )

    pl_header_row = report_rows[0]
    bs_header_row = report_rows[1]

    # Dates for P&L and Balance Sheet sections (assumed aligned)
    pl_dates = pd.to_datetime(df.iloc[pl_header_row, 1:], errors="coerce")
    bs_dates = pd.to_datetime(df.iloc[bs_header_row, 1:], errors="coerce")

    if not pl_dates.equals(bs_dates):
        # Align by intersection if, for any reason, the dates differ
        common = sorted(set(pl_dates.dropna()) & set(bs_dates.dropna()))
        if not common:
            raise ValueError("No common report dates between P&L and Balance Sheet sections.")
        # Reindex rows on common dates
        def extract_row_after(header_row: int, label: str) -> pd.Series:
            row_idx = df.index[(df.index > header_row) & (df[0] == label)].min()
            if pd.isna(row_idx):
                raise ValueError(f"Row labeled '{label}' not found after header row {header_row}.")
            vals = pd.to_numeric(df.iloc[row_idx, 1:], errors="coerce")
            ser = pd.Series(vals.values, index=pd.to_datetime(df.iloc[header_row, 1:], errors="coerce"))
            return ser.loc[common]

        revenue = extract_row_after(pl_header_row, "Sales")
        cash_like = extract_row_after(pl_header_row, "Net profit")
        borrowings = extract_row_after(bs_header_row, "Borrowings")
        equity_share = extract_row_after(bs_header_row, "Equity Share Capital")
        reserves = extract_row_after(bs_header_row, "Reserves")
        equity = equity_share + reserves
        return revenue, cash_like, borrowings, equity

    # Happy path: same dates for P&L and Balance Sheet
    dates = pl_dates

    def extract_row_after(header_row: int, label: str) -> pd.Series:
        # Find first row after header_row whose first cell matches label
        candidates = df.index[(df.index > header_row) & (df[0] == label)]
        if len(candidates) == 0:
            raise ValueError(f"Row labeled '{label}' not found after header row {header_row}.")
        row_idx = candidates.min()
        vals = pd.to_numeric(df.iloc[row_idx, 1:], errors="coerce")
        return pd.Series(vals.values, index=dates)

    revenue_series = extract_row_after(pl_header_row, "Sales")
    cash_flow_series = extract_row_after(pl_header_row, "Net profit")
    debt_series = extract_row_after(bs_header_row, "Borrowings")

    equity_share = extract_row_after(bs_header_row, "Equity Share Capital")
    reserves = extract_row_after(bs_header_row, "Reserves")
    equity_series = equity_share + reserves

    return revenue_series, cash_flow_series, debt_series, equity_series


# ---------------------------------------------------------------------------
# Orchestration / pipeline
# ---------------------------------------------------------------------------

def run_pipeline(entity_id: str, excel_path: str = "HCL Technologies.xlsx") -> Dict[str, Any]:
    """Run the full explainable background check pipeline for a single entity.

    By default this uses time-series data loaded from the given Excel file.
    To revert to synthetic mock data, you can swap this implementation for
    the earlier mock-data generator.
    """
    # --- 1. Load monthly time-series data from Excel ------------------------
    revenue_series, cash_flow_series, debt_series, equity_series = load_timeseries_from_excel(
        excel_path
    )

    # --- 2. Initialize agents -----------------------------------------------
    rev_agent = RevenueStabilityAgent()
    cf_agent = CashFlowAgent()
    debt_agent = LiabilityDebtAgent()
    xref_agent = CrossReferenceAgent()

    # --- 3. Run individual agents -------------------------------------------
    rev_output = rev_agent.run(entity_id, revenue_series)
    cf_output = cf_agent.run(entity_id, cash_flow_series)
    debt_output = debt_agent.run(entity_id, debt_series, equity_series)

    # --- 4. Cross-reference agent -------------------------------------------
    xref_output = xref_agent.run(entity_id, rev_output, cf_output, debt_output)

    # --- 5. Apply rule-based review layer -----------------------------------
    rules = apply_review_rules(entity_id, rev_output, cf_output, debt_output, xref_output)

    # --- 6. Construct a final, human-readable explanation -------------------
    final_explanation = build_human_explanation(
        entity_id, rev_output, cf_output, debt_output, xref_output, rules
    )

    # Package all structured outputs for potential downstream use
    return {
        "entity_id": entity_id,
        "revenue_agent": asdict(rev_output),
        "cashflow_agent": asdict(cf_output),
        "debt_agent": asdict(debt_output),
        "cross_reference_agent": asdict(xref_output),
        "rules": [rule.__dict__ for rule in rules],
        "final_explanation": final_explanation,
    }


# ---------------------------------------------------------------------------
# Explanation builder
# ---------------------------------------------------------------------------

def build_human_explanation(
    entity_id: str,
    rev_output: AgentOutput,
    cf_output: AgentOutput,
    debt_output: AgentOutput,
    xref_output: CrossReferenceOutput,
    rules: List[RuleResult],
) -> str:
    """
    Build a narrative explanation of how the results were reached.

    This is intentionally verbose and references:
    - Each agent's main metrics and assessment.
    - Cross-agent consistency/conflict analysis.
    - Explicitly triggered guardrail rules.
    """
    lines: List[str] = []
    lines.append(f"Explainable financial background check for entity '{entity_id}'")
    lines.append("=" * 72)
    lines.append("")

    # Revenue
    rev = rev_output.metrics["revenue"]
    lines.append("1. Revenue Stability Agent")
    lines.append("   ------------------------")
    lines.append(
        f"   Trend: {rev.trend_direction} "
        f"(slope {rev.trend_slope_per_step:.2f} per month)."
    )
    lines.append(
        f"   Volatility: {rev.volatility:.2f} "
        f"(classified as {rev.volatility_label})."
    )
    lines.append(f"   Persistence: {rev.persistence_description}.")
    lines.append(f"   Assessment: {rev_output.overall_assessment}")
    for note in rev_output.notes:
        lines.append(f"   Note: {note}")
    lines.append("")

    # Cash flow
    cf = cf_output.metrics["cash_flow"]
    lines.append("2. Cash Flow Agent")
    lines.append("   ----------------")
    lines.append(
        f"   Trend: {cf.trend_direction} "
        f"(slope {cf.trend_slope_per_step:.2f} per month)."
    )
    lines.append(
        f"   Volatility: {cf.volatility:.2f} "
        f"(classified as {cf.volatility_label})."
    )
    lines.append(f"   Persistence: {cf.persistence_description}.")
    negative_cf_share = float(cf_output.inputs_summary["negative_month_share"])
    avg_cf = float(cf_output.inputs_summary["average_cash_flow"])
    lines.append(
        f"   Average monthly cash flow: {avg_cf:.2f}; "
        f"{negative_cf_share*100:.1f}% of months negative."
    )
    lines.append(f"   Assessment: {cf_output.overall_assessment}")
    for note in cf_output.notes:
        lines.append(f"   Note: {note}")
    lines.append("")

    # Debt / leverage
    debt = debt_output.metrics["debt"]
    equity = debt_output.metrics["equity"]
    lev = debt_output.metrics["leverage"]
    latest_leverage = float(
        debt_output.inputs_summary.get("latest_debt_to_equity", float("nan"))
    )
    lines.append("3. Liability / Debt Agent")
    lines.append("   -----------------------")
    lines.append(
        f"   Debt trend: {debt.trend_direction} "
        f"(slope {debt.trend_slope_per_step:.2f})."
    )
    lines.append(
        f"   Equity trend: {equity.trend_direction} "
        f"(slope {equity.trend_slope_per_step:.2f})."
    )
    lines.append(
        f"   Latest debt/equity ratio: {latest_leverage:.2f} "
        f"(trend: {lev.trend_direction}, "
        f"slope {lev.trend_slope_per_step:.2f})."
    )
    lines.append(f"   Assessment: {debt_output.overall_assessment}")
    for note in debt_output.notes:
        lines.append(f"   Note: {note}")
    lines.append("")

    # Cross-reference
    lines.append("4. Cross-Reference Agent")
    lines.append("   ----------------------")
    lines.append(f"   Summary: {xref_output.overall_summary}")
    if xref_output.consistencies:
        lines.append("   Consistencies:")
        for c in xref_output.consistencies:
            lines.append(f"     - {c}")
    if xref_output.conflicts:
        lines.append("   Conflicts:")
        for c in xref_output.conflicts:
            lines.append(f"     - {c}")
    if xref_output.risk_indicators:
        lines.append("   Risk indicators:")
        for r in xref_output.risk_indicators:
            lines.append(f"     - {r}")
    if not (
        xref_output.consistencies
        or xref_output.conflicts
        or xref_output.risk_indicators
    ):
        lines.append("   No notable consistencies or conflicts identified.")
    lines.append("")

    # Rules
    lines.append("5. Rule-based Review Layer (Guardrails Only)")
    lines.append("   -----------------------------------------")
    triggered_rules = [r for r in rules if r.triggered]
    if triggered_rules:
        lines.append("   The following rules were triggered and should prompt manual review:")
        for r in triggered_rules:
            lines.append(f"     - {r.rule_id}: {r.description}")
            if r.reason:
                lines.append(f"       Reason: {r.reason}")
    else:
        lines.append("   No rules were triggered. No automatic decisions are made.")
    lines.append("")

    lines.append(
        "Note: This system does NOT issue approve/reject decisions. "
        "All outputs are intended to support human judgment with "
        "traceable, interpretable statistics."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    entity_id = "ENTITY_12345"

    results = run_pipeline(entity_id)

    # Print structured parts and then the human explanation
    print("=== Structured Outputs (summary) ===")
    print(f"Entity ID: {results['entity_id']}")
    print(f"- Revenue agent overall assessment: {results['revenue_agent']['overall_assessment']}")
    print(f"- Cash flow agent overall assessment: {results['cashflow_agent']['overall_assessment']}")
    print(f"- Debt agent overall assessment: {results['debt_agent']['overall_assessment']}")
    print(f"- Cross-reference summary: {results['cross_reference_agent']['overall_summary']}")

    triggered_rules = [r for r in results["rules"] if r["triggered"]]
    print(f"- Triggered rules: {[r['rule_id'] for r in triggered_rules]}")
    print()

    print("=== Full Explainability Report ===")
    print(results["final_explanation"])


if __name__ == "__main__":
    main()
