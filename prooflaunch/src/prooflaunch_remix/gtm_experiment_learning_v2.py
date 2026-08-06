from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMExperimentLearningBundleV2"
FACTORS = {"creative", "channel", "audience", "offer"}
CAUSAL_DESIGNS = {"randomized_holdout", "geo_holdout", "time_holdout", "matched_control"}
ATTRIBUTION_DESIGNS = CAUSAL_DESIGNS | {"descriptive_multi_touch"}
OUTCOME_CHAIN = ("qualified_attention", "proof_consumption", "owned_signal", "activation", "sale", "fulfillment", "retention", "profit")
MONITORING_SIGNALS = ("creative_fatigue", "excessive_frequency", "negative_feedback", "audience_overlap", "cac_increase", "retention_decline")
NEGATIVE_SIGNAL_TYPES = ("comment_objection", "lost_deal", "refund", "churn", "low_quality_lead", "platform_rejection")
MATRIX_DIMENSIONS = ("mechanism_id", "subvertical_id", "company_scale", "lifecycle_state", "budget_tier", "market")


class GTMExperimentLearningError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _text(row: Mapping[str, Any], field: str, minimum: int = 4) -> str:
    value = str(row.get(field) or "").strip()
    if len(value) < minimum:
        raise GTMExperimentLearningError(f"{field} is missing or too thin")
    return value


def compile_experiment_learning_bundle(
    experiments: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    memory_candidates: Sequence[Mapping[str, Any]],
    effect_matrix: Sequence[Mapping[str, Any]],
    allocations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized_experiments = []
    experiment_ids: set[str] = set()
    for raw in experiments:
        experiment_id = _text(raw, "experiment_id")
        if experiment_id in experiment_ids:
            raise GTMExperimentLearningError("experiment IDs must be unique")
        experiment_ids.add(experiment_id)
        factors = [str(value) for value in raw.get("factors_changed") or []]
        if not factors or not set(factors).issubset(FACTORS) or len(factors) != len(set(factors)):
            raise GTMExperimentLearningError("experiment factors are invalid")
        factorial = raw.get("factorial_design")
        if len(factors) > 1 and (not isinstance(factorial, Mapping) or int(factorial.get("cells", 0)) < 4 or not factorial.get("design_type")):
            raise GTMExperimentLearningError("multi-factor experiment lacks a declared factorial design")
        design = str(raw.get("attribution_design") or "")
        if design not in ATTRIBUTION_DESIGNS:
            raise GTMExperimentLearningError("attribution design is unsupported")
        if raw.get("causal_claim_planned") is True and design not in CAUSAL_DESIGNS:
            raise GTMExperimentLearningError("causal claim is planned from descriptive attribution")
        monitoring = raw.get("monitoring_thresholds")
        if not isinstance(monitoring, Mapping) or set(monitoring) != set(MONITORING_SIGNALS):
            raise GTMExperimentLearningError("all six fatigue and economics thresholds are required")
        if any(float(value) < 0 for value in monitoring.values()):
            raise GTMExperimentLearningError("monitoring thresholds cannot be negative")
        normalized_experiments.append({
            "experiment_id": experiment_id,
            "mechanism_id": _text(raw, "mechanism_id"),
            "audience_id": _text(raw, "audience_id"),
            "hypothesis": _text(raw, "hypothesis", 16),
            "primary_metric": _text(raw, "primary_metric"),
            "guardrails": list(raw.get("guardrails") or []),
            "duration_days": int(raw.get("duration_days", 0)),
            "sample_plan": _text(raw, "sample_plan", 8),
            "cost_ceiling_usd": float(raw.get("cost_ceiling_usd", 0)),
            "stop_rule": _text(raw, "stop_rule", 12),
            "factors_changed": factors,
            "factorial_design": dict(factorial) if isinstance(factorial, Mapping) else None,
            "attribution_design": design,
            "multi_touch_role": "descriptive_only" if design == "descriptive_multi_touch" else "not_primary",
            "causal_claim_planned": bool(raw.get("causal_claim_planned")),
            "monitoring_thresholds": dict(monitoring),
            "status": "preregistered_not_executed",
            "external_execution_authority": False,
        })
        if not normalized_experiments[-1]["guardrails"] or normalized_experiments[-1]["duration_days"] <= 0 or normalized_experiments[-1]["cost_ceiling_usd"] < 0:
            raise GTMExperimentLearningError("experiment guardrails, duration, or cost are invalid")

    normalized_outcomes = []
    outcome_by_experiment: dict[str, dict[str, Any]] = {}
    eval_tasks = []
    for raw in outcomes:
        experiment_id = str(raw.get("experiment_id") or "")
        if experiment_id not in experiment_ids or experiment_id in outcome_by_experiment:
            raise GTMExperimentLearningError("outcome has unknown or duplicate experiment lineage")
        result_status = str(raw.get("result_status") or "")
        if result_status not in {"succeeded", "failed", "inconclusive"}:
            raise GTMExperimentLearningError("outcome status is invalid")
        failure_reason = str(raw.get("failure_reason") or "").strip()
        if result_status == "failed" and len(failure_reason) < 8:
            raise GTMExperimentLearningError("failed experiment must retain a failure reason")
        signals = list(raw.get("negative_signals") or [])
        for signal in signals:
            if signal.get("signal_type") not in NEGATIVE_SIGNAL_TYPES or len(str(signal.get("summary") or "")) < 8:
                raise GTMExperimentLearningError("negative signal is invalid")
            eval_tasks.append({
                "eval_task_id": f"eval:{experiment_id}:{len(eval_tasks)+1}",
                "experiment_id": experiment_id,
                "signal_type": signal["signal_type"],
                "failure_coordinate": str(signal["summary"]),
                "required_next_test": str(signal.get("required_next_test") or "Reproduce and isolate the failure before a new promotion."),
                "automatic_strategy_mutation_allowed": False,
            })
        row = {
            "experiment_id": experiment_id,
            "result_status": result_status,
            "failure_reason": failure_reason or None,
            "evidence_status": str(raw.get("evidence_status") or "unverified"),
            "outcome_chain": list(OUTCOME_CHAIN),
            "primary_metric_effect": raw.get("primary_metric_effect"),
            "confidence_interval": raw.get("confidence_interval"),
            "negative_signals": signals,
            "human_verified": bool(raw.get("human_verified")),
        }
        normalized_outcomes.append(row); outcome_by_experiment[experiment_id] = row

    memory_rows = []
    promoted_memory = []
    for raw in memory_candidates:
        experiment_id = str(raw.get("experiment_id") or "")
        outcome = outcome_by_experiment.get(experiment_id)
        if outcome is None:
            raise GTMExperimentLearningError("memory candidate lacks outcome lineage")
        approval = raw.get("human_approval")
        approved = bool(
            outcome["human_verified"]
            and isinstance(approval, Mapping)
            and approval.get("decision") == "approved_for_long_term_memory"
            and len(str(approval.get("approver_name") or "").strip()) >= 3
        )
        row = {
            "experiment_id": experiment_id,
            "memory_statement": _text(raw, "memory_statement", 16),
            "outcome_human_verified": outcome["human_verified"],
            "human_approval": dict(approval) if isinstance(approval, Mapping) else None,
            "promotion_status": "promoted_verified_human_approved" if approved else "not_promoted",
        }
        memory_rows.append(row)
        if approved: promoted_memory.append(row)

    matrix_rows = []
    for raw in effect_matrix:
        if any(not raw.get(field) for field in MATRIX_DIMENSIONS):
            raise GTMExperimentLearningError("effect matrix key is incomplete")
        estimate = float(raw.get("effect_estimate"))
        lower = float(raw.get("ci_lower")); upper = float(raw.get("ci_upper"))
        if lower > estimate or estimate > upper:
            raise GTMExperimentLearningError("effect estimate is outside its confidence interval")
        matrix_rows.append({**{field: raw[field] for field in MATRIX_DIMENSIONS}, "effect_metric": _text(raw, "effect_metric"), "effect_estimate": estimate, "ci_lower": lower, "ci_upper": upper, "evidence_status": str(raw.get("evidence_status") or "unknown")})

    allocation_rows = []
    for raw in allocations:
        exploration = float(raw.get("exploration_share", -1)); exploitation = float(raw.get("exploitation_share", -1))
        platform = {str(key): float(value) for key, value in (raw.get("platform_shares") or {}).items()}
        creative = {str(key): float(value) for key, value in (raw.get("creative_family_shares") or {}).items()}
        if abs(exploration + exploitation - 1) > 1e-9 or not 0 <= exploration <= 1 or not platform or not creative or max(platform.values()) > .5 or max(creative.values()) > .5 or abs(sum(platform.values()) - 1) > 1e-9 or abs(sum(creative.values()) - 1) > 1e-9:
            raise GTMExperimentLearningError("exploration/exploitation or correlation-risk allocation is invalid")
        allocation_rows.append({"mechanism_id": _text(raw, "mechanism_id"), "exploration_share": exploration, "exploitation_share": exploitation, "platform_shares": platform, "creative_family_shares": creative, "single_platform_or_creative_cap": .5})

    payload = {
        "schema": SCHEMA,
        "experiments": normalized_experiments,
        "outcomes": normalized_outcomes,
        "evaluation_tasks_from_negative_signals": eval_tasks,
        "memory_candidates": memory_rows,
        "promoted_memory_count": len(promoted_memory),
        "effect_matrix": matrix_rows,
        "allocations": allocation_rows,
        "unified_outcome_chain": list(OUTCOME_CHAIN),
        "policy": {
            "multi_touch_is_descriptive_only": True,
            "failed_results_are_retained": True,
            "memory_requires_verified_outcome_and_named_human_approval": True,
            "automatic_strategy_or_memory_mutation_allowed": False,
            "external_experiment_execution_allowed": False,
        },
        "truth_boundary": "The bundle proves experiment and learning controls. Synthetic fixtures and preregistration do not prove execution, lift, causality, or future performance.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_experiment_learning_bundle(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMExperimentLearningError("experiment-learning seal is invalid")
    if payload.get("unified_outcome_chain") != list(OUTCOME_CHAIN):
        raise GTMExperimentLearningError("outcome chain drifted")
    promoted = sum(row.get("promotion_status") == "promoted_verified_human_approved" for row in payload.get("memory_candidates", []))
    if payload.get("promoted_memory_count") != promoted:
        raise GTMExperimentLearningError("memory promotion aggregate drifted")
    if payload.get("policy", {}).get("automatic_strategy_or_memory_mutation_allowed") is not False or payload.get("policy", {}).get("external_experiment_execution_allowed") is not False:
        raise GTMExperimentLearningError("learning bundle escaped authority")


__all__ = ["GTMExperimentLearningError", "compile_experiment_learning_bundle", "verify_experiment_learning_bundle"]
