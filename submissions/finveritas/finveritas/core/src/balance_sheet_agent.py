"""Balance Sheet Stability Agent

Consumes OCR-produced Bloomberg financial statement JSON files (see `output/`).
Computes balance-sheet metrics deterministically in Python and uses an LLM only
for explanation.

Hard constraints:
- All numeric computations happen in Python (pandas/numpy).
- The LLM must not compute numbers; it only explains provided metrics.
- The LLM must use only provided metrics.
"""

from __future__ import annotations

import json
import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from src import db as _db

RiskLevel = Literal["low", "moderate", "high"]
Trend = Literal["increasing", "declining", "stable"]


# ------------------------------
# IO
# ------------------------------

def load_json(path: str | Path) -> dict[str, Any]:
    """Load a single OCR output JSON file."""
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


def write_agent_output(*, payload: dict[str, Any], output_dir: str | Path) -> Path:
    """Write the agent output to `{output_dir}/{entity}_balance_sheet.json`."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    entity = str(payload.get("entity") or "UNKNOWN")
    safe = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in entity).strip()
    safe = safe.replace(" ", "_") or "UNKNOWN"

    out_path = out_dir / f"{safe}_balance_sheet.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


# ------------------------------
# Period handling
# ------------------------------

_PERIOD_RE = re.compile(r"^(?P<year>\d{4})-(?P<tag>FY|Q[1-4])$")


def _period_sort_key(period: str) -> tuple[int, int]:
    """Sort key for 'YYYY-FY' / 'YYYY-QN' periods."""
    m = _PERIOD_RE.match(period.strip())
    if not m:
        raise ValueError(
            f"Unsupported period format: {period!r} (expected 'YYYY-FY' or 'YYYY-QN')"
        )
    year = int(m.group("year"))
    tag = m.group("tag")
    if tag == "FY":
        return year, 5
    return year, int(tag[1:])


def _to_series_map(items: Any, field_name: str) -> dict[str, float]:
    """Convert a time_series[field] array into {period -> value}, dropping nulls."""
    if items is None:
        return {}
    if not isinstance(items, list):
        raise ValueError(f"Expected time_series.{field_name} to be a list")

    out: dict[str, float] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        p = it.get("period")
        v = it.get("value")
        if not isinstance(p, str) or not p.strip() or v is None:
            continue
        try:
            vf = float(v)
        except (TypeError, ValueError):
            continue
        if np.isnan(vf):
            continue
        out[p.strip()] = vf

    return out


# ------------------------------
# Extraction + validation
# ------------------------------


def extract_balance_sheet_data(payload: dict[str, Any]) -> tuple[str, pd.DataFrame]:
    """Extract required balance-sheet series and return an aligned DataFrame.

    Required fields:
    - total_assets
    - total_liabilities
    - equity

    Optional fields (ignored for core metrics but can be used later):
    - current_assets
    - current_liabilities

    Validation:
    - require >=4 aligned periods
    - periods sorted chronologically
    """

    entity = payload.get("entity") or {}
    entity_id = str(entity.get("entity_id") or "UNKNOWN")

    ts = payload.get("time_series")
    if not isinstance(ts, dict):
        raise ValueError("Missing or invalid 'time_series' in JSON")

    ta = _to_series_map(ts.get("total_assets"), "total_assets")
    tl = _to_series_map(ts.get("total_liabilities"), "total_liabilities")
    eq = _to_series_map(ts.get("equity"), "equity")

    common = set(ta) & set(tl) & set(eq)
    if len(common) < 4:
        raise ValueError(
            "Need at least 4 periods with total_assets/total_liabilities/equity present. "
            f"Got {len(common)}"
        )

    periods = sorted(common, key=_period_sort_key)

    df = pd.DataFrame(
        {
            "period": periods,
            "total_assets": [ta[p] for p in periods],
            "total_liabilities": [tl[p] for p in periods],
            "equity": [eq[p] for p in periods],
        }
    )

    # Negative values are generally suspicious here.
    for col in ["total_assets", "total_liabilities", "equity"]:
        if (df[col] < 0).any():
            bad = df.loc[df[col] < 0, ["period", col]].to_dict("records")
            raise ValueError(f"Negative values detected for {col}: {bad}")

    # Accounting identity check: assets ≈ liabilities + equity.
    # Raise a warning when mismatch > 5%.
    implied_assets = df["total_liabilities"] + df["equity"]
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = (df["total_assets"] - implied_assets).abs() / df["total_assets"].replace(0, np.nan)

    if rel.notna().any() and float(rel.max()) > 0.05:
        max_pct = float(rel.max() * 100.0)
        warnings.warn(
            f"Accounting identity mismatch > 5% detected. Max mismatch={max_pct:.2f}%.",
            RuntimeWarning,
        )

    return entity_id, df


# ------------------------------
# Deterministic metrics
# ------------------------------


@dataclass(frozen=True)
class BalanceSheetMetrics:
    asset_growth_rate: float
    liability_growth_rate: float
    equity_growth_rate: float
    leverage_ratio: float
    balance_sheet_risk: RiskLevel

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_growth_rate": float(self.asset_growth_rate),
            "liability_growth_rate": float(self.liability_growth_rate),
            "equity_growth_rate": float(self.equity_growth_rate),
            "leverage_ratio": float(self.leverage_ratio),
            "balance_sheet_risk": self.balance_sheet_risk,
        }


def _avg_yoy_growth_pct(series: pd.Series) -> float:
    growth = series.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if growth.empty:
        raise ValueError("Insufficient data to compute YoY growth")
    return float(growth.mean() * 100.0)


def _trend_from_slope(*, slope: float, scale: float) -> Trend:
    if scale == 0:
        return "stable"
    norm = slope / scale
    if norm > 0.01:
        return "increasing"
    if norm < -0.01:
        return "declining"
    return "stable"


def compute_balance_sheet_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """Compute deterministic balance-sheet metrics."""

    work = df.copy()

    asset_growth_rate = _avg_yoy_growth_pct(work["total_assets"])
    liability_growth_rate = _avg_yoy_growth_pct(work["total_liabilities"])
    equity_growth_rate = _avg_yoy_growth_pct(work["equity"])

    # Leverage ratio series and average.
    if (work["equity"] == 0).any():
        bad = work.loc[work["equity"] == 0, "period"].tolist()
        raise ValueError(f"equity is 0 for periods {bad}; cannot compute leverage ratio")

    work["leverage_ratio"] = work["total_liabilities"] / work["equity"]
    avg_leverage_ratio = float(work["leverage_ratio"].mean())

    # Trend direction (internal; not exposed in final metrics schema).
    x = np.arange(len(work), dtype=float)
    lev = work["leverage_ratio"].to_numpy(dtype=float)
    lev_slope = float(np.polyfit(x, lev, deg=1)[0])
    leverage_trend = _trend_from_slope(slope=lev_slope, scale=float(np.mean(np.abs(lev))) or 1.0)

    balance_sheet_risk = classify_balance_sheet_risk(
        leverage_ratio=avg_leverage_ratio,
        leverage_trend=leverage_trend,
        asset_growth_rate=asset_growth_rate,
        liability_growth_rate=liability_growth_rate,
        equity_growth_rate=equity_growth_rate,
    )

    metrics = BalanceSheetMetrics(
        asset_growth_rate=asset_growth_rate,
        liability_growth_rate=liability_growth_rate,
        equity_growth_rate=equity_growth_rate,
        leverage_ratio=avg_leverage_ratio,
        balance_sheet_risk=balance_sheet_risk,
    )

    return {
        "metrics": metrics.to_dict(),
        "intermediate": {
            "leverage_trend": leverage_trend,
        },
    }


def classify_balance_sheet_risk(
    *,
    leverage_ratio: float,
    leverage_trend: Trend,
    asset_growth_rate: float,
    liability_growth_rate: float,
    equity_growth_rate: float,
) -> RiskLevel:
    """Classify balance-sheet risk deterministically."""

    expansion_ok = asset_growth_rate >= liability_growth_rate
    equity_positive = equity_growth_rate > 0

    # High risk conditions
    if leverage_ratio > 3:
        return "high"
    if (liability_growth_rate > asset_growth_rate) and (equity_growth_rate <= 0):
        return "high"

    # Low risk conditions
    if leverage_ratio < 2 and expansion_ok and equity_positive:
        return "low"

    # Moderate default
    if 2 <= leverage_ratio <= 3:
        return "moderate"

    # If leverage is <2 but other conditions fail, treat as moderate.
    # If leverage is >3 already handled above.
    return "moderate"


# ------------------------------
# LangChain explanation
# ------------------------------


def generate_llm_explanation(
    *,
    entity: str,
    metrics: dict[str, Any],
    model: str,
    base_url: str,
    api_key: str,
    run_id: str | None = None,
) -> str:
    """Generate explanation text using only computed metrics."""

    system = (
        "You are a financial risk analyst. "
        "You must not calculate, estimate, or infer any new numbers. "
        "Use only the provided metrics. "
        "Do not provide credit, lending, or investment recommendations. "
        "Write in a concise, professional tone (4-8 sentences)."
    )

    human = {
        "task": "Explain balance sheet stability and leverage using ONLY the provided metrics.",
        "entity": entity,
        "metrics": metrics,
        "notes": [
            "Do not introduce new numbers, ranges, or time horizons.",
            "Do not reference financial line items that are not in the metrics.",
        ],
    }

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
    messages = [SystemMessage(content=system), HumanMessage(content=json.dumps(human, indent=2))]

    resp = _db.instrumented_invoke(
        llm, messages,
        run_id=run_id, agent_name="balance_sheet_agent", model=model, base_url=base_url,
    )

    text = getattr(resp, "content", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("LLM returned empty explanation")

    return text.strip()


# ------------------------------
# Final output
# ------------------------------


def build_final_output(*, entity: str, metrics: dict[str, Any], analysis: str) -> dict[str, Any]:
    return {"entity": entity, "metrics": metrics, "analysis": analysis}


def run_balance_sheet_agent(
    *,
    json_path: str | Path,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload = load_json(json_path)
    entity, df = extract_balance_sheet_data(payload)

    computed = compute_balance_sheet_metrics(df)
    metrics = computed["metrics"]

    # Defaults to Qwen-compatible settings; can be overridden for local demos.
    resolved_model = model or os.environ.get("BS_AGENT_MODEL", "qwen-plus")
    resolved_base_url = base_url or os.environ.get(
        "BS_AGENT_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    resolved_api_key = api_key or os.environ.get("QWEN_API_KEY") or os.environ.get("BS_AGENT_API_KEY")
    if not resolved_api_key:
        raise ValueError(
            "Missing API key for LLM explanation. Set QWEN_API_KEY (or pass --api-key)."
        )

    analysis = generate_llm_explanation(
        entity=entity,
        metrics=metrics,
        model=resolved_model,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        run_id=run_id,
    )

    return build_final_output(entity=entity, metrics=metrics, analysis=analysis)


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Balance Sheet Agent (deterministic metrics + LLM explanation)")
    ap.add_argument("--json", required=True, help="Path to an OCR output JSON")
    ap.add_argument("--model", default=None, help="LLM model (default: qwen-plus)")
    ap.add_argument("--base-url", default=None, help="OpenAI-compatible base URL")
    ap.add_argument("--api-key", default=None, help="API key (default: env QWEN_API_KEY)")
    ap.add_argument(
        "--out-dir",
        default="balance_sheet_output",
        help="Directory to write the agent output JSON (default: balance_sheet_output/)",
    )
    args = ap.parse_args()

    out = run_balance_sheet_agent(
        json_path=args.json,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
    )

    written = write_agent_output(payload=out, output_dir=args.out_dir)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nWrote: {written}")


if __name__ == "__main__":
    _main()
