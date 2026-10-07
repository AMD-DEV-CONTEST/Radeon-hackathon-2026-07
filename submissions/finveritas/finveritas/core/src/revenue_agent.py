"""Revenue Agent

Loads an OCR-produced JSON (from this repo's `output/` folder), extracts the
revenue time series, computes deterministic metrics, and uses an LLM *only* to
turn the metrics into a brief professional explanation.

Design constraints:
- All numeric computations happen in Python (pandas/numpy).
- The LLM must not compute numbers; it only explains provided metrics.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from src import db as _db

TrendDirection = Literal["increasing", "declining", "stable"]


# ------------------------------
# IO
# ------------------------------

def load_json(path: str | Path) -> dict[str, Any]:
    """Load a single OCR output JSON file.

    Raises:
        FileNotFoundError: if path does not exist.
        ValueError: if JSON is malformed or not a dict.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"JSON not found: {p}")

    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {p}") from e

    if not isinstance(obj, dict):
        raise ValueError(f"Expected top-level JSON object in {p}")

    return obj


# ------------------------------
# Revenue parsing + validation
# ------------------------------

_PERIOD_RE = re.compile(r"^(?P<year>\d{4})-(?P<tag>FY|Q[1-4])$")


def _period_sort_key(period: str) -> tuple[int, int]:
    """Sortable key for periods like '2024-FY' or '2024-Q2'."""
    m = _PERIOD_RE.match(period.strip())
    if not m:
        raise ValueError(
            f"Unsupported period format: {period!r} (expected 'YYYY-FY' or 'YYYY-QN')"
        )

    year = int(m.group("year"))
    tag = m.group("tag")
    if tag == "FY":
        # Ensure FY sorts after all quarters within the same year if ever mixed.
        return year, 5

    q = int(tag[1:])
    return year, q


def _extract_revenue_series(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    entity = payload.get("entity") or {}
    entity_id = entity.get("entity_id") or "UNKNOWN"

    ts = payload.get("time_series")
    if not isinstance(ts, dict):
        raise ValueError("Missing or invalid 'time_series' in JSON")

    revenue = ts.get("revenue")
    if revenue is None:
        raise ValueError("Missing 'time_series.revenue' in JSON")
    if not isinstance(revenue, list):
        raise ValueError("Expected 'time_series.revenue' to be a list")

    return str(entity_id), revenue


def _validate_and_frame(revenue: list[dict[str, Any]]) -> pd.DataFrame:
    """Validate revenue records and return a canonical DataFrame.

    Validation requirements:
    - Minimum 4 periods
    - No null values
    - No negative values
    - Chronological ordering (as provided)
    """
    if len(revenue) < 4:
        raise ValueError(f"Need at least 4 revenue periods; got {len(revenue)}")

    rows: list[dict[str, Any]] = []
    for i, item in enumerate(revenue):
        if not isinstance(item, dict):
            raise ValueError(f"Revenue item at index {i} is not an object")

        period = item.get("period")
        value = item.get("value")

        if period is None or not isinstance(period, str) or not period.strip():
            raise ValueError(f"Revenue item at index {i} missing valid 'period'")

        # Disallow nulls/NaNs.
        if value is None:
            raise ValueError(f"Revenue value is null for period {period}")
        try:
            value_f = float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Revenue value is not numeric for period {period}: {value!r}") from e

        if np.isnan(value_f):
            raise ValueError(f"Revenue value is NaN for period {period}")
        if value_f < 0:
            raise ValueError(f"Revenue value is negative for period {period}: {value_f}")

        rows.append({"period": period.strip(), "revenue": value_f})

    df = pd.DataFrame(rows)

    # Validate unique periods.
    if df["period"].duplicated().any():
        dups = df[df["period"].duplicated()]["period"].tolist()
        raise ValueError(f"Duplicate revenue periods found: {dups}")

    # Validate chronological ordering (as provided) using the sortable key.
    provided_periods = df["period"].tolist()
    sorted_periods = sorted(provided_periods, key=_period_sort_key)
    if provided_periods != sorted_periods:
        raise ValueError(
            "Revenue periods are not in chronological order. "
            f"Provided={provided_periods} Sorted={sorted_periods}"
        )

    # Attach sortable keys for downstream use.
    df["_year"], df["_sub" ] = zip(*(_period_sort_key(p) for p in df["period"]))

    return df


# ------------------------------
# Metrics
# ------------------------------


@dataclass(frozen=True)
class RevenueMetrics:
    avg_growth: float
    cagr: float
    volatility: float
    positive_growth_ratio: float
    trend_direction: TrendDirection

    def to_dict(self) -> dict[str, Any]:
        return {
            "avg_growth": float(self.avg_growth),
            "cagr": float(self.cagr),
            "volatility": float(self.volatility),
            "positive_growth_ratio": float(self.positive_growth_ratio),
            "trend_direction": self.trend_direction,
        }


def compute_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """Compute deterministic revenue metrics.

    Returns a dict containing:
    - metrics: RevenueMetrics (as dict)
    - intermediate: series and regression info (internal use for trend classification / prompting)

    Notes:
    - YoY growth is computed as pct_change on revenue and expressed in percent.
    - Volatility is std-dev of YoY growth (percentage points).
    - Linear regression slope is computed on raw revenue vs integer time index.
    """
    series = df[["period", "revenue"]].copy()

    # YoY growth in percent (first is NaN)
    series["yoy_growth_pct"] = series["revenue"].pct_change() * 100.0

    growth = series["yoy_growth_pct"].replace([np.inf, -np.inf], np.nan).dropna()
    if growth.empty:
        raise ValueError("Insufficient valid growth observations to compute growth metrics")

    avg_growth = float(growth.mean())
    volatility = float(growth.std(ddof=0))

    positive_growth_ratio = float((growth > 0).mean())

    first = float(series["revenue"].iloc[0])
    last = float(series["revenue"].iloc[-1])
    n_periods = int(series.shape[0])
    years = n_periods - 1

    if years < 1:
        raise ValueError("Need at least 2 revenue points to compute CAGR")
    if first <= 0:
        raise ValueError("Cannot compute CAGR when the first revenue value is <= 0")

    cagr = float(((last / first) ** (1.0 / years) - 1.0) * 100.0)

    # Linear regression slope (revenue units per period)
    x = np.arange(n_periods, dtype=float)
    y = series["revenue"].to_numpy(dtype=float)
    slope = float(np.polyfit(x, y, deg=1)[0])

    trend = classify_trend(slope=slope, revenue_mean=float(np.mean(y)))

    metrics = RevenueMetrics(
        avg_growth=avg_growth,
        cagr=cagr,
        volatility=volatility,
        positive_growth_ratio=positive_growth_ratio,
        trend_direction=trend,
    )

    return {
        "metrics": metrics.to_dict(),
        "intermediate": {
            "periods": series["period"].tolist(),
            "revenue": [float(v) for v in series["revenue"].tolist()],
            "yoy_growth_pct": [None if pd.isna(v) else float(v) for v in series["yoy_growth_pct"].tolist()],
            "regression_slope": slope,
        },
    }


def classify_trend(*, slope: float, revenue_mean: float) -> TrendDirection:
    """Classify trend direction using a normalized slope threshold.

    We normalize slope by mean revenue to reduce sensitivity to company scale.

    Thresholds are intentionally simple/deterministic (production-friendly).
    """
    if revenue_mean == 0:
        return "stable"

    normalized = slope / revenue_mean  # per-period, fraction of mean

    # 1% of mean per period threshold.
    if normalized > 0.01:
        return "increasing"
    if normalized < -0.01:
        return "declining"
    return "stable"


# ------------------------------
# LangChain explanation
# ------------------------------


def build_prompt(*, entity: str, metrics: dict[str, Any]) -> list[Any]:
    """Build chat messages for the explanation step.

    IMPORTANT: Some local models will "helpfully" convert ratios (e.g. 0.875)
    to percentages (87.5%). To keep the output deterministic and compliant, we
    exclude ratio-valued metrics from the LLM prompt and have the LLM focus on
    the growth/trend metrics only.

    The prompt is designed to:
    - Force the model to use only the provided metrics
    - Avoid any additional calculations or financial advice
    """

    metrics_for_llm = {
        "avg_growth": metrics.get("avg_growth"),
        "cagr": metrics.get("cagr"),
        "volatility": metrics.get("volatility"),
        "trend_direction": metrics.get("trend_direction"),
    }

    system = (
        "You are a financial analytics assistant writing a short explanation of revenue performance. "
        "Hard rules: (1) Do NOT calculate, estimate, or infer any new numbers. "
        "(2) Use ONLY the provided metrics; do not reference any other financial data (costs, margins, profits, cash flow, balance sheet). "
        "(3) Do NOT give credit, lending, or investment recommendations. "
        "(4) Keep a constrained, professional tone and be concise (4-8 sentences)."
    )

    human = {
        "task": "Explain the revenue metrics using ONLY the provided values.",
        "entity": entity,
        "metric_definitions": {
            "avg_growth": "Average year-over-year (YoY) revenue growth, in percent.",
            "cagr": "Compound annual growth rate over the full span, in percent.",
            "volatility": "Standard deviation of YoY revenue growth (percentage points).",
            "trend_direction": "Direction based on linear regression slope of revenue over time: increasing/declining/stable.",
        },
        "metrics": metrics_for_llm,
        "output": {
            "requirements": [
                "Only discuss revenue growth and trend",
                "Do not mention profitability, spending, margins, or costs",
                "Do not mention specific years/periods or the length of the time horizon",
                "Reference trend_direction explicitly",
                "No new numbers or ranges",
            ]
        },
    }

    return [SystemMessage(content=system), HumanMessage(content=json.dumps(human, indent=2))]


def generate_explanation(
    *,
    entity: str,
    metrics: dict[str, Any],
    model: str,
    base_url: str,
    api_key: str,
    run_id: str | None = None,
) -> str:
    """Generate a narrative explanation via LangChain.

    IMPORTANT: This function must never pass raw time series to the LLM.
    Only the computed metrics are included.

    Note: Ratio-valued metrics are excluded from the prompt in `build_prompt()`
    to avoid non-deterministic conversions (e.g., 0.875 → 87.5%).
    """

    llm = ChatOpenAI(
        model=model,
        temperature=0,
        base_url=base_url,
        api_key=api_key,
    )

    messages = build_prompt(entity=entity, metrics=metrics)
    resp = _db.instrumented_invoke(
        llm, messages,
        run_id=run_id, agent_name="revenue_agent", model=model, base_url=base_url,
    )

    text = getattr(resp, "content", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("LLM returned empty explanation")

    return text.strip()


# ------------------------------
# Orchestration
# ------------------------------


def run_revenue_agent(
    *,
    json_path: str | Path,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run the full agent: load → compute → explain."""

    payload = load_json(json_path)
    entity, revenue_series = _extract_revenue_series(payload)
    df = _validate_and_frame(revenue_series)

    computed = compute_metrics(df)
    metrics = computed["metrics"]

    resolved_model = model or os.environ.get(
        "REVENUE_AGENT_MODEL", "qwen2.5-coder-1.5b-instruct-mlx"
    )
    resolved_base_url = base_url or os.environ.get(
        "REVENUE_AGENT_BASE_URL", "http://127.0.0.1:1234/v1"
    )
    resolved_api_key = api_key or os.environ.get("REVENUE_AGENT_API_KEY", "local")

    analysis = generate_explanation(
        entity=entity,
        metrics=metrics,
        model=resolved_model,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        run_id=run_id,
    )

    return {
        "entity": entity,
        "metrics": metrics,
        "analysis": analysis,
    }


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Revenue Agent (deterministic metrics + LLM explanation)")
    ap.add_argument(
        "--json",
        required=True,
        help="Path to an OCR output JSON (e.g. output/Company.json)",
    )
    ap.add_argument(
        "--model",
        default=None,
        help="Model identifier (default: env REVENUE_AGENT_MODEL or qwen2.5-coder-1.5b-instruct-mlx)",
    )
    ap.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible base URL (default: env REVENUE_AGENT_BASE_URL or http://127.0.0.1:1234/v1)",
    )
    args = ap.parse_args()

    out = run_revenue_agent(json_path=args.json, model=args.model, base_url=args.base_url)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
