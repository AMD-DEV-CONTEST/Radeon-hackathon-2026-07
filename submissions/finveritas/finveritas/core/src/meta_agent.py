"""Meta-Orchestrator — self-aware pipeline supervisor.

After all domain agents complete, this agent:
1. Scores confidence for each agent output (data completeness, metric health).
2. Detects drift by comparing current metrics against the most recent prior run
   for the same entity stored in the SQLite audit log.
3. Surfaces guardrail violations logged during this run.
4. Optionally generates an LLM advisory summarising what to trust and what to verify.

All numeric reasoning is deterministic — the LLM (if invoked) receives only a
structured summary dict, never raw time-series data.
"""
from __future__ import annotations

import json
import statistics
from typing import Any

from src import db as _db


# Keys we expect each agent's metrics dict to populate
_EXPECTED_KEYS: dict[str, list[str]] = {
    "revenue": [
        "cagr", "avg_yoy_growth", "revenue_volatility",
        "trend_direction", "peak_revenue", "trough_revenue",
    ],
    "liquidity": [
        "current_ratio", "quick_ratio", "cash_ratio",
        "operating_cf_ratio", "cash_burn_rate",
    ],
    "balance_sheet": [
        "debt_to_equity", "total_liabilities_to_assets",
        "solvency_ratio", "equity_growth_trend",
    ],
    "sentiment": [
        "positive_ratio", "negative_ratio", "neutral_ratio",
        "article_count", "sentiment_label",
    ],
}

# Pairs used for drift detection: (output_key, metric_key, human_label)
_DRIFT_PAIRS: list[tuple[str, str, str]] = [
    ("revenue",       "cagr",               "Revenue CAGR"),
    ("liquidity",     "current_ratio",       "Current Ratio"),
    ("balance_sheet", "debt_to_equity",      "Debt/Equity"),
    ("balance_sheet", "solvency_ratio",      "Solvency Ratio"),
]

# DB agent_name → output dict key mapping
_DB_TO_KEY: dict[str, str] = {
    "revenue_agent":         "revenue",
    "liquidity_agent":       "liquidity",
    "balance_sheet_agent":   "balance_sheet",
    "sentiment_agent":       "sentiment",
    "cross_reference_agent": "cross_reference",
}


# ── Confidence scoring ────────────────────────────────────────────────────────

def _completeness_score(metrics: dict | None, expected_keys: list[str]) -> int:
    """0-60: proportion of expected keys that are non-None."""
    if not metrics or not expected_keys:
        return 0
    present = sum(1 for k in expected_keys if metrics.get(k) is not None)
    return int(60 * present / len(expected_keys))


def _health_deductions(metrics: dict | None, agent_key: str) -> int:
    """0-20: penalty for red-flag metric values."""
    if not metrics:
        return 0
    penalty = 0
    if agent_key == "liquidity":
        cr = metrics.get("current_ratio")
        if isinstance(cr, (int, float)):
            if cr < 0:
                penalty += 20
            elif cr < 0.5:
                penalty += 12
            elif cr < 1.0:
                penalty += 6
    if agent_key == "balance_sheet":
        de = metrics.get("debt_to_equity")
        if isinstance(de, (int, float)) and de > 10:
            penalty += 10
    if agent_key == "revenue":
        cagr = metrics.get("cagr")
        if isinstance(cagr, (int, float)) and cagr < -0.4:
            penalty += 10
    return min(penalty, 20)


def score_agent(output: dict, agent_key: str) -> int:
    """Return 0-100 confidence score for a single agent output.

    0 means the agent errored or was skipped.
    """
    if isinstance(output.get("error"), str):
        return 0
    if agent_key == "cross_reference":
        # Cross-ref has no numeric metrics — score on text presence
        return 85 if (output.get("analysis") or "").strip() else 20

    metrics = output.get("metrics") or {}
    expected = _EXPECTED_KEYS.get(agent_key, [])
    base = _completeness_score(metrics, expected)
    penalty = _health_deductions(metrics, agent_key)
    # +20 baseline for having a result at all
    return max(0, min(100, base + 20 - penalty))


# ── Drift detection ───────────────────────────────────────────────────────────

def detect_drift(
    entity: str,
    current_outputs: dict[str, Any],
    db_path=None,
) -> list[str]:
    """Compare key metrics against the most recent prior run for the same entity.

    Returns a list of human-readable alert strings; empty list means no drift.
    """
    alerts: list[str] = []
    try:
        all_runs = _db.query_runs(db_path)
        entity_runs = [r for r in all_runs if r.get("entity") == entity]
        if len(entity_runs) < 2:
            return alerts  # no prior run to compare against

        prior_run_id = entity_runs[1]["run_id"]
        prior_agents = {
            a["agent_name"]: a
            for a in _db.query_run_agents(prior_run_id, db_path)
        }

        for out_key, metric_key, label in _DRIFT_PAIRS:
            db_agent_name = f"{out_key}_agent"
            prior_row = prior_agents.get(db_agent_name)
            if not prior_row or not prior_row.get("metrics_json"):
                continue
            try:
                prior_metrics = json.loads(prior_row["metrics_json"])
            except Exception:
                continue

            prior_v = prior_metrics.get(metric_key)
            curr_metrics = (current_outputs.get(out_key) or {}).get("metrics") or {}
            curr_v = curr_metrics.get(metric_key)

            if prior_v is None or curr_v is None:
                continue
            try:
                pv, cv = float(prior_v), float(curr_v)
                if abs(pv) > 1e-9:
                    change_pct = abs(cv - pv) / abs(pv) * 100
                    if change_pct > 25:
                        direction = "↑" if cv > pv else "↓"
                        alerts.append(
                            f"{label} {direction} {change_pct:.0f}% vs prior run "
                            f"({pv:.3g} → {cv:.3g})"
                        )
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    return alerts


# ── Main entry point ──────────────────────────────────────────────────────────

def run_meta_agent(
    entity: str,
    outputs: dict[str, Any],
    *,
    run_id: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    db_path=None,
) -> dict[str, Any]:
    """Self-aware meta-assessment over all domain agent outputs.

    Returns a dict with keys:
      entity, overall_confidence, confidence_label,
      per_agent_confidence, drift_alerts, flags,
      violations_by_agent, advisory (optional).
    """
    per_agent: dict[str, int] = {}
    for key in ("revenue", "liquidity", "balance_sheet", "sentiment", "cross_reference"):
        per_agent[key] = score_agent(outputs.get(key) or {}, key)

    # Pull guardrail violations from this run's LLM call log
    violations_by_agent: dict[str, int] = {}
    if run_id:
        try:
            for lc in _db.query_run_llm_calls(run_id, db_path):
                if lc.get("violations_found"):
                    aname = lc.get("agent_name", "")
                    violations_by_agent[aname] = violations_by_agent.get(aname, 0) + 1
        except Exception:
            pass

    # Deduct confidence for agents that triggered the guardrail
    for db_name, penalty in [(k, v * 15) for k, v in violations_by_agent.items()]:
        out_key = _DB_TO_KEY.get(db_name)
        if out_key and out_key in per_agent:
            per_agent[out_key] = max(0, per_agent[out_key] - penalty)

    valid_scores = [s for s in per_agent.values() if s > 0]
    overall = int(statistics.mean(valid_scores)) if valid_scores else 0

    drift_alerts = detect_drift(entity, outputs, db_path)

    # Build actionable flag list
    flags: list[str] = []
    for key, score in per_agent.items():
        out = outputs.get(key) or {}
        err = out.get("error", "")
        label = key.replace("_", " ").title()
        if score == 0:
            if "skipped" in str(err).lower():
                flags.append(f"{label}: skipped — missing required data fields.")
            elif isinstance(err, str) and err:
                flags.append(f"{label}: failed — {str(err)[:80]}")
        elif score < 55:
            flags.append(
                f"{label}: low confidence ({score}/100) — check data completeness."
            )

    for alert in drift_alerts:
        flags.append(f"DRIFT: {alert}")

    for agent_db_name, count in violations_by_agent.items():
        flags.append(
            f"GUARDRAIL: {agent_db_name} triggered credit-decision filter "
            f"{count}× — review narrative in Compliance tab."
        )

    confidence_label = "HIGH" if overall >= 80 else "MEDIUM" if overall >= 55 else "LOW"

    result: dict[str, Any] = {
        "entity": entity,
        "overall_confidence": overall,
        "confidence_label": confidence_label,
        "per_agent_confidence": per_agent,
        "drift_alerts": drift_alerts,
        "flags": flags,
        "violations_by_agent": violations_by_agent,
        "agents_assessed": 5,
        "agents_succeeded": sum(1 for s in per_agent.values() if s > 0),
    }

    # Optional LLM advisory — only when the pipeline LLM is configured
    _key_ok = api_key and api_key.strip().lower() not in {
        "", "local", "not-needed", "api key",
        "google ai studio key", "groq api key",
    }
    if base_url and model and _key_ok and overall > 0:
        try:
            result["advisory"] = _generate_advisory(
                entity, result, base_url, model, api_key, run_id, db_path
            )
        except Exception as exc:
            result["advisory_error"] = str(exc)

    return result


def _generate_advisory(
    entity: str,
    assessment: dict,
    base_url: str,
    model: str,
    api_key: str,
    run_id: str | None,
    db_path,
) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    system = (
        "You are the Meta-Orchestrator for a financial analysis system. "
        "You have reviewed all sub-agent outputs and their confidence scores. "
        "Write a 4-6 sentence analyst advisory that: "
        "(1) states the overall confidence level and why; "
        "(2) names which specific agents or metrics warrant extra scrutiny; "
        "(3) mentions any metric drift if alerts are present; "
        "(4) recommends the next human review action. "
        "Do NOT make credit, lending, or investment recommendations. "
        "Write in third person, concise professional tone."
    )
    human = json.dumps({
        "entity": entity,
        "overall_confidence": assessment["overall_confidence"],
        "confidence_label": assessment["confidence_label"],
        "per_agent_confidence": assessment["per_agent_confidence"],
        "drift_alerts": assessment["drift_alerts"],
        "flags": assessment["flags"],
    }, indent=2)

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
    messages = [SystemMessage(content=system), HumanMessage(content=human)]

    resp = _db.instrumented_invoke(
        llm, messages,
        run_id=run_id,
        agent_name="meta_agent",
        model=model,
        base_url=base_url,
        db_path=db_path,
    )
    return (getattr(resp, "content", "") or "").strip()
