"""Revenue Stability Agent prototype.

Requirements addressed:
- Loads quarterly revenue time-series from local `as.json` (only data source).
- Uses pandas for time-series handling and deterministic numerical analysis.
- Computes, without any LLM involvement:
  * Trend (direction + slope)
  * Volatility (standard deviation relative to mean)
  * Persistence (% of periods with revenue increase vs. prior period)
- Classifies volatility and persistence using explicit, documented thresholds.
- Uses Groq API (lightweight model, e.g. `llama3-8b-8192`) ONLY to
  generate a natural-language explanation. The LLM is explicitly
  instructed NOT to compute numbers, classify risk, or predict.
- Produces an audit-friendly output that clearly separates:
  1. Raw data
  2. Computed metrics
  3. LLM-generated explanation

Execution:
- Ensure `pandas`, `numpy`, and `requests` are installed.
- Ensure `as.json` is present in the same directory as this script.
- Set environment variable `GROQ_API_KEY` with your Groq API key.
- Run:  python revenue_stability_agent.py
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests


AS_FILE_NAME = "as.json"
GROQ_API_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL_NAME = "llama-3.1-8b-instant"  # lightweight model per requirements


@dataclass
class EntityInfo:
    entity_id: str
    type: str
    industry: str
    currency: str


@dataclass
class RevenuePoint:
    period: str
    value: float


@dataclass
class TrendMetrics:
    slope_absolute: float  # change in revenue per period (same unit as revenue)
    slope_relative: Optional[float]  # slope / mean_revenue (unitless), None if mean == 0
    direction: str  # "upward", "downward", or "flat"
    # Explicit tolerance used to classify direction to avoid over-interpreting noise
    direction_tolerance_relative: float


@dataclass
class VolatilityMetrics:
    mean_revenue: float
    std_deviation: float
    coefficient_of_variation: Optional[float]  # std / mean, None if mean == 0
    classification: str  # "low", "moderate", "high", or "undefined"
    thresholds: Dict[str, float]


@dataclass
class PersistenceMetrics:
    num_periods: int
    num_transitions: int
    num_increases: int
    num_decreases: int
    num_flat: int
    persistence_ratio: Optional[float]  # increases / transitions, None if <2 periods
    classification: str  # "high", "moderate", "low", or "undefined"
    thresholds: Dict[str, float]


@dataclass
class RevenueStabilityResult:
    entity: EntityInfo
    metadata: Dict[str, Any]
    raw_revenue: List[RevenuePoint]
    trend: TrendMetrics
    volatility: VolatilityMetrics
    persistence: PersistenceMetrics


def load_as_json(file_name: str = AS_FILE_NAME) -> Dict[str, Any]:
    """Load the mandatory `as.json` file from the current directory.

    This is the only data source; no financial values are hardcoded.
    """

    path = os.path.join(os.path.dirname(__file__), file_name)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def extract_entity_info(data: Dict[str, Any]) -> EntityInfo:
    entity = data.get("entity", {})
    return EntityInfo(
        entity_id=str(entity.get("entity_id", "unknown")),
        type=str(entity.get("type", "unknown")),
        industry=str(entity.get("industry", "unknown")),
        currency=str(entity.get("currency", "unknown")),
    )


def extract_revenue_series(data: Dict[str, Any]) -> List[RevenuePoint]:
    """Extract revenue time series in original order from the JSON structure.

    The order in `as.json` is treated as the canonical chronological order.
    No sorting or reindexing is applied.
    """

    ts = data.get("time_series", {})
    revenue_entries = ts.get("revenue", [])

    revenue_series: List[RevenuePoint] = []
    for entry in revenue_entries:
        period = str(entry.get("period"))
        value = float(entry.get("value"))
        revenue_series.append(RevenuePoint(period=period, value=value))

    return revenue_series


def build_revenue_dataframe(revenue_series: List[RevenuePoint]) -> pd.DataFrame:
    """Build a pandas DataFrame for the revenue series.

    The DataFrame preserves the original ordering of periods as they appear
    in `as.json`. The index is a simple RangeIndex representing successive
    observed periods.
    """

    df = pd.DataFrame(
        {
            "period": [p.period for p in revenue_series],
            "revenue": [p.value for p in revenue_series],
        }
    )
    return df


def compute_trend_metrics(df: pd.DataFrame) -> TrendMetrics:
    """Compute trend direction and slope using deterministic linear regression.

    Implementation details:
    - Uses a simple ordinary least squares fit of revenue against the
      period index (0, 1, 2, ...) via `numpy.polyfit`.
    - Slope is expressed in revenue units per period.
    - Relative slope is slope divided by mean revenue (if mean != 0).
    - Direction classification uses an explicit relative tolerance to
      avoid overstating very small slopes as meaningful trends.

    Direction thresholds (explicit):
    - Compute abs(slope_relative).
    - If mean_revenue == 0 or fewer than 2 observations: direction = "flat".
    - If abs(slope_relative) < 0.01 (i.e., <1% of mean per period): "flat".
    - Else if slope > 0: "upward".
    - Else: "downward".
    """

    revenues = df["revenue"].astype(float).to_numpy()
    n = len(revenues)
    if n < 2:
        # Not enough data to infer a meaningful trend.
        mean_revenue = float(revenues.mean()) if n == 1 else 0.0
        return TrendMetrics(
            slope_absolute=0.0,
            slope_relative=None if mean_revenue == 0 else 0.0,
            direction="flat",
            direction_tolerance_relative=0.01,
        )

    x = np.arange(n, dtype=float)
    # polyfit returns slope and intercept for degree=1.
    slope, _intercept = np.polyfit(x, revenues, deg=1)
    mean_revenue = float(revenues.mean())

    slope_relative: Optional[float]
    if mean_revenue == 0:
        slope_relative = None
    else:
        slope_relative = float(slope / mean_revenue)

    tolerance = 0.01  # 1% of mean revenue per period

    if mean_revenue == 0 or slope_relative is None:
        direction = "flat"
    else:
        if abs(slope_relative) < tolerance:
            direction = "flat"
        elif slope > 0:
            direction = "upward"
        else:
            direction = "downward"

    return TrendMetrics(
        slope_absolute=float(slope),
        slope_relative=slope_relative,
        direction=direction,
        direction_tolerance_relative=tolerance,
    )


def classify_volatility(cv: Optional[float]) -> Tuple[str, Dict[str, float]]:
    """Classify volatility based on coefficient of variation.

    Volatility measure:
    - coefficient_of_variation = std_deviation / mean_revenue

    Explicit thresholds (conservative, unitless):
    - If cv is None: classification = "undefined".
    - Else:
        * cv < 0.05  -> "low"       (std < 5% of mean)
        * 0.05 <= cv < 0.15 -> "moderate" (5%-15% of mean)
        * cv >= 0.15 -> "high"      (>=15% of mean)

    These are descriptive, not prescriptive, and do NOT represent
    regulatory or risk limits.
    """

    thresholds = {
        "low_upper": 0.05,
        "moderate_upper": 0.15,
    }

    if cv is None:
        return "undefined", thresholds

    if cv < thresholds["low_upper"]:
        classification = "low"
    elif cv < thresholds["moderate_upper"]:
        classification = "moderate"
    else:
        classification = "high"

    return classification, thresholds


def compute_volatility_metrics(df: pd.DataFrame) -> VolatilityMetrics:
    revenues = df["revenue"].astype(float).to_numpy()
    mean_revenue = float(revenues.mean()) if len(revenues) > 0 else 0.0

    if len(revenues) == 0:
        std_dev = 0.0
    else:
        # Population standard deviation (ddof=0) for stability over small samples.
        std_dev = float(np.std(revenues, ddof=0))

    if mean_revenue == 0:
        cv = None
    else:
        cv = float(std_dev / mean_revenue)

    classification, thresholds = classify_volatility(cv)

    return VolatilityMetrics(
        mean_revenue=mean_revenue,
        std_deviation=std_dev,
        coefficient_of_variation=cv,
        classification=classification,
        thresholds=thresholds,
    )


def classify_persistence(persistence_ratio: Optional[float]) -> Tuple[str, Dict[str, float]]:
    """Classify persistence of revenue increases.

    Persistence measure:
    - persistence_ratio = (# of periods with an increase) / (# of transitions)
      where a transition is any move from one period to the next.

    Explicit thresholds:
    - If ratio is None: classification = "undefined".
    - Else:
        * ratio >= 0.75 -> "high"      (increases in >=75% of transitions)
        * 0.50 <= ratio < 0.75 -> "moderate" (increases in 50%-75%)
        * ratio < 0.50 -> "low"        (increases in <50%)

    These thresholds are descriptive and do not imply any forecast or
    judgment about future performance.
    """

    thresholds = {
        "high_lower": 0.75,
        "moderate_lower": 0.50,
    }

    if persistence_ratio is None:
        return "undefined", thresholds

    if persistence_ratio >= thresholds["high_lower"]:
        classification = "high"
    elif persistence_ratio >= thresholds["moderate_lower"]:
        classification = "moderate"
    else:
        classification = "low"

    return classification, thresholds


def compute_persistence_metrics(df: pd.DataFrame) -> PersistenceMetrics:
    revenues = df["revenue"].astype(float).to_numpy()
    n = len(revenues)

    if n < 2:
        return PersistenceMetrics(
            num_periods=n,
            num_transitions=0,
            num_increases=0,
            num_decreases=0,
            num_flat=0,
            persistence_ratio=None,
            classification="undefined",
            thresholds={
                "high_lower": 0.75,
                "moderate_lower": 0.50,
            },
        )

    deltas = np.diff(revenues)
    num_increases = int(np.sum(deltas > 0))
    num_decreases = int(np.sum(deltas < 0))
    num_flat = int(np.sum(deltas == 0))
    num_transitions = len(deltas)

    if num_transitions == 0:
        persistence_ratio = None
    else:
        persistence_ratio = float(num_increases / num_transitions)

    classification, thresholds = classify_persistence(persistence_ratio)

    return PersistenceMetrics(
        num_periods=n,
        num_transitions=num_transitions,
        num_increases=num_increases,
        num_decreases=num_decreases,
        num_flat=num_flat,
        persistence_ratio=persistence_ratio,
        classification=classification,
        thresholds=thresholds,
    )


def run_revenue_stability_agent() -> RevenueStabilityResult:
    """Run the Revenue Stability Agent end-to-end (excluding LLM explanation)."""

    data = load_as_json(AS_FILE_NAME)

    entity_info = extract_entity_info(data)
    revenue_series = extract_revenue_series(data)
    metadata = data.get("metadata", {})

    df_revenue = build_revenue_dataframe(revenue_series)

    trend = compute_trend_metrics(df_revenue)
    volatility = compute_volatility_metrics(df_revenue)
    persistence = compute_persistence_metrics(df_revenue)

    return RevenueStabilityResult(
        entity=entity_info,
        metadata=metadata,
        raw_revenue=revenue_series,
        trend=trend,
        volatility=volatility,
        persistence=persistence,
    )


def build_llm_prompt(result: RevenueStabilityResult) -> str:
    """Construct a prompt for Groq to generate a descriptive explanation.

    The LLM is used **only** for natural-language explanation. All
    numerical values and classifications are pre-computed deterministically
    by this script and must not be altered by the LLM.
    """

    # Prepare a minimal, structured summary for the LLM.
    raw_revenue = [asdict(rp) for rp in result.raw_revenue]

    payload = {
        "entity": asdict(result.entity),
        "metadata": result.metadata,
        "raw_revenue": raw_revenue,
        "trend": asdict(result.trend),
        "volatility": asdict(result.volatility),
        "persistence": asdict(result.persistence),
    }

    # The instructions explicitly prohibit numerical computation,
    # classification, risk assessment, or forecasting by the LLM.
    prompt = (
        "You are assisting in a financial risk review by providing a "
        "neutral, descriptive summary of historical revenue stability. "
        "You must **not** perform any numerical calculations, you must **not** "
        "re-compute metrics, you must **not** re-classify risk or volatility, "
        "and you must **not** make any predictions or forward-looking statements.\n\n"
        "You are given pre-computed metrics for quarterly revenue. "
        "Your role is only to restate, in clear natural language, what these "
        "metrics already show. Describe patterns in revenue, trend direction, "
        "volatility classification, and persistence classification exactly as "
        "they are provided, without altering values or adding new ones.\n\n"
        "Use a professional, neutral tone appropriate for a financial risk "
        "review. Focus on what is observable from the data and metrics; do not "
        "infer management intent, strategy, or future outcomes.\n\n"
        "Here is the structured input (JSON):\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Write a concise narrative of 2–4 paragraphs."
    )

    return prompt


def generate_groq_explanation(result: RevenueStabilityResult) -> Optional[str]:
    """Call the Groq API to obtain a natural-language explanation.

    If `GROQ_API_KEY` is not set or the request fails, returns None and the
    rest of the analysis remains fully available for audit.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    prompt = build_llm_prompt(result)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = {
        "model": GROQ_MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful financial analyst. You must only create "
                    "natural-language summaries based on provided metrics. You "
                    "must not perform calculations or change the metrics."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 600,
    }

    try:
        response = requests.post(GROQ_API_BASE_URL, headers=headers, json=body, timeout=30)
        # Basic debug logging for troubleshooting Groq failures.
        print(f"[DEBUG] Groq response status: {response.status_code}")
        try:
            print(f"[DEBUG] Groq response body: {response.text[:500]}")
        except Exception:
            # If response.text fails for any reason, ignore.
            pass
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            print("[DEBUG] Groq response has no choices field")
            return None
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            print("[DEBUG] Groq response message has no content field")
        return content
    except Exception as e:
        # In a regulated prototype, we fail safely by omitting the
        # narrative if the LLM call does not succeed, but we print
        # debug information to help diagnose the issue.
        print(f"[DEBUG] Groq API call failed: {e}")
        return None


def print_audit_friendly_output(result: RevenueStabilityResult, explanation: Optional[str]) -> None:
    """Print raw data, computed metrics, and LLM explanation separately."""

    print("=== REVENUE STABILITY AGENT OUTPUT ===")

    # 1. Raw data
    print("\n[1] RAW REVENUE DATA (from as.json, preserved order)")
    raw_block = {
        "entity": asdict(result.entity),
        "metadata": result.metadata,
        "revenue": [asdict(rp) for rp in result.raw_revenue],
    }
    print(json.dumps(raw_block, indent=2))

    # 2. Computed metrics (deterministic, no LLM involvement)
    print("\n[2] COMPUTED METRICS")
    metrics_block = {
        "trend": asdict(result.trend),
        "volatility": asdict(result.volatility),
        "persistence": asdict(result.persistence),
    }
    print(json.dumps(metrics_block, indent=2))

    # 3. LLM-generated explanation (if available)
    print("\n[3] LLM-GENERATED EXPLANATION (Groq)")
    if explanation is None:
        print(
            "No explanation generated. Either GROQ_API_KEY was not set or the "
            "Groq API request did not succeed."
        )
    else:
        print(explanation)


def main() -> None:
    result = run_revenue_stability_agent()
    explanation = generate_groq_explanation(result)
    print_audit_friendly_output(result, explanation)


if __name__ == "__main__":
    main()
