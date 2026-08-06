from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


SCHEMA = "ProofLaunchLaunchProofControlV1"
GATE_IDS = (
    "local_regression",
    "portfolio_human_preference",
    "judge_calibration",
    "production_guardrails",
    "production_trace_coverage",
    "remote_required_ci",
    "radeon_key_inference",
    "production_effect",
    "causal_revenue",
)


class LaunchProofControlError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mapping(value: object, schema: str, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema") != schema:
        raise LaunchProofControlError(f"{name} status is unavailable or invalid")
    return value


def _gate(
    gate_id: str,
    *,
    passed: bool,
    observed: bool,
    summary: str,
    evidence: Mapping[str, Any],
    next_action: str,
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "passed": bool(passed),
        "observed": bool(observed),
        "summary": summary,
        "evidence": dict(evidence),
        "next_action": None if passed else next_action,
    }


def compile_launch_proof_control(
    *,
    product_readiness: Mapping[str, Any],
    portfolio_status: Mapping[str, Any],
    judge_status: Mapping[str, Any],
    guardrail_status: Mapping[str, Any],
    trace_status: Mapping[str, Any],
    radeon_receipt: Mapping[str, Any] | None,
) -> dict[str, Any]:
    readiness = _mapping(
        product_readiness,
        "ProofLaunchAug3ProductReadinessV1",
        "product readiness",
    )
    portfolio = _mapping(
        portfolio_status,
        "ProofLaunchPortfolioBlindReviewQueueStatusV1",
        "portfolio blind review",
    )
    judge = _mapping(
        judge_status,
        "ProofLaunchJudgeCalibrationStatusV1",
        "judge calibration",
    )
    guardrails = _mapping(
        guardrail_status,
        "ProofLaunchProductionGuardrailStatusV1",
        "guardrail telemetry",
    )
    traces = _mapping(
        trace_status,
        "ProofLaunchProductionTraceStatusV1",
        "request trace",
    )
    verification = readiness.get("verification")
    if not isinstance(verification, Mapping):
        raise LaunchProofControlError("product readiness verification is invalid")

    local_regression = bool(
        isinstance(verification.get("product_critical_regression"), Mapping)
        and verification["product_critical_regression"].get("passed") is True
    )
    portfolio_observed = int(portfolio.get("submitted_review_count", 0)) > 0
    portfolio_passed = bool(
        portfolio.get("review_complete") is True
        and portfolio.get("portfolio_promotion_passed") is True
        and portfolio.get("human_preference_observed") is True
    )
    judge_observed = int(judge.get("submitted_review_count", 0)) > 0
    judge_passed = bool(
        judge.get("review_complete") is True
        and judge.get("judge_calibrated") is True
    )
    guardrail_observed = bool(
        guardrails.get("production_deployment_observed") is True
        and int(guardrails.get("event_count", 0)) > 0
    )
    guardrail_passed = bool(
        guardrail_observed
        and guardrails.get("hash_chain_valid") is True
        and guardrails.get("raw_content_retained") is False
    )
    trace_observed = bool(
        traces.get("production_deployment_observed") is True
        and int(traces.get("request_trace_count", 0)) > 0
    )
    trace_passed = bool(
        trace_observed
        and traces.get("hash_chain_valid") is True
        and traces.get("raw_content_retained") is False
        and int(traces.get("retention_days", 0)) >= 90
    )
    remote_ci = verification.get("production_trace_remote_required_check_observed") is True

    radeon_observed = bool(
        isinstance(radeon_receipt, Mapping)
        and radeon_receipt.get("schema") == "ProofLaunchRadeonLivePreflightV1"
        and radeon_receipt.get("radeon_runtime_observed") is True
    )
    radeon_passed = bool(
        radeon_observed
        and radeon_receipt is not None
        and radeon_receipt.get("preflight_passed") is True
        and radeon_receipt.get("model_inference_observed") is True
    )
    production_outcomes = int(
        verification.get("lifecycle_closure_production_outcomes_observed", 0)
    )
    production_effect = bool(
        production_outcomes > 0
        and verification.get("gtm_cockpit_four_a_effect_claim_eligible") is True
    )
    causal_revenue = bool(
        verification.get("revenue_feedback_causal_revenue_claim_allowed") is True
    )

    gates = [
        _gate(
            "local_regression",
            passed=local_regression,
            observed=local_regression,
            summary="Product-critical deterministic regression",
            evidence={"passed": local_regression},
            next_action="Run the product-critical suite and repair every failure.",
        ),
        _gate(
            "portfolio_human_preference",
            passed=portfolio_passed,
            observed=portfolio_observed,
            summary="Nine-case B2B/B2C portfolio blind preference",
            evidence={
                "submitted": int(portfolio.get("submitted_review_count", 0)),
                "expected": int(portfolio.get("expected_review_count", 0)),
                "complete": portfolio.get("review_complete") is True,
                "promotion_passed": portfolio.get("portfolio_promotion_passed") is True,
            },
            next_action="Complete all invitation-bound portfolio reviews with five independent named humans.",
        ),
        _gate(
            "judge_calibration",
            passed=judge_passed,
            observed=judge_observed,
            summary="Binary model judge calibrated against frozen human labels",
            evidence={
                "submitted": int(judge.get("submitted_review_count", 0)),
                "expected": int(judge.get("expected_review_count", 0)),
                "complete": judge.get("review_complete") is True,
                "judge_calibrated": judge.get("judge_calibrated") is True,
            },
            next_action="Complete all 300 labels, adjudicate disagreements, and require TPR/TNR strictly above 0.80.",
        ),
        _gate(
            "production_guardrails",
            passed=guardrail_passed,
            observed=guardrail_observed,
            summary="Input/output guardrails observed on deployed traffic",
            evidence={
                "event_count": int(guardrails.get("event_count", 0)),
                "blocked_event_count": int(guardrails.get("blocked_event_count", 0)),
                "deployment_observed": guardrails.get("production_deployment_observed") is True,
                "hash_chain_valid": guardrails.get("hash_chain_valid") is True,
            },
            next_action="Deploy the instrumented boundary and seal human-reviewed hit, false-block, and escape metrics.",
        ),
        _gate(
            "production_trace_coverage",
            passed=trace_passed,
            observed=trace_observed,
            summary="All deployed requests retained as content-free traces",
            evidence={
                "request_trace_count": int(traces.get("request_trace_count", 0)),
                "deployment_observed": traces.get("production_deployment_observed") is True,
                "retention_days": int(traces.get("retention_days", 0)),
                "hash_chain_valid": traces.get("hash_chain_valid") is True,
            },
            next_action="Compare load-balancer request counts with retained traces and retain the verified 90-day window.",
        ),
        _gate(
            "remote_required_ci",
            passed=remote_ci,
            observed=remote_ci,
            summary="Remote protected CI required check",
            evidence={"required_check_observed": remote_ci},
            next_action="Run the remote workflow and configure its successful check as branch-protection required.",
        ),
        _gate(
            "radeon_key_inference",
            passed=radeon_passed,
            observed=radeon_observed,
            summary="Key model inference observed locally on AMD Radeon/ROCm",
            evidence={
                "runtime_observed": radeon_observed,
                "preflight_passed": bool(radeon_receipt and radeon_receipt.get("preflight_passed") is True),
                "model_inference_observed": bool(radeon_receipt and radeon_receipt.get("model_inference_observed") is True),
            },
            next_action="Run the frozen key inference on Hello ROCm and seal hardware, model, input, output, latency, and memory hashes.",
        ),
        _gate(
            "production_effect",
            passed=production_effect,
            observed=production_outcomes > 0,
            summary="Real production effect and 4A preference evidence",
            evidence={
                "production_outcomes_observed": production_outcomes,
                "four_a_effect_claim_eligible": verification.get("gtm_cockpit_four_a_effect_claim_eligible") is True,
            },
            next_action="Import source-bound real experiment outcomes and complete independent human craft review.",
        ),
        _gate(
            "causal_revenue",
            passed=causal_revenue,
            observed=causal_revenue,
            summary="Causal revenue claim backed by experiment and reconciled economics",
            evidence={"causal_revenue_claim_allowed": causal_revenue},
            next_action="Complete a preregistered comparison and reconcile discounts, refunds, chargebacks, COGS, fees, media, model, and operator cost.",
        ),
    ]
    passed_count = sum(gate["passed"] for gate in gates)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "gate_count": len(gates),
        "passed_gate_count": passed_count,
        "blocked_gate_count": len(gates) - passed_count,
        "launch_decision": (
            "production_promotion_eligible"
            if passed_count == len(gates)
            else "blocked_pending_external_evidence"
        ),
        "gates": gates,
        "next_actions": [
            gate["next_action"] for gate in gates if gate["next_action"] is not None
        ],
        "automatic_publish_enabled": False,
        "automatic_spend_enabled": False,
        "automatic_strategy_mutation_enabled": False,
        "four_a_claim_allowed": production_effect,
        "top1_claim_allowed": False,
        "causal_revenue_claim_allowed": causal_revenue,
        "truth_boundary": (
            "This dynamic control reports only current hash-bound service and evidence states. "
            "A local pass cannot substitute for named human labels, deployed traffic, remote CI, "
            "Radeon-local inference, production effect, causal revenue, or external ranking evidence."
        ),
    }
    receipt["content_sha256"] = _digest(receipt)
    validate_launch_proof_control(receipt)
    return receipt


def validate_launch_proof_control(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA:
        raise LaunchProofControlError("launch proof schema is invalid")
    unsigned = dict(receipt)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise LaunchProofControlError("launch proof digest is invalid")
    gates = receipt.get("gates")
    if not isinstance(gates, list) or tuple(gate.get("gate_id") for gate in gates) != GATE_IDS:
        raise LaunchProofControlError("launch proof gates are invalid")
    passed = sum(gate.get("passed") is True for gate in gates)
    if (
        receipt.get("gate_count") != len(GATE_IDS)
        or receipt.get("passed_gate_count") != passed
        or receipt.get("blocked_gate_count") != len(GATE_IDS) - passed
    ):
        raise LaunchProofControlError("launch proof counts are invalid")
    eligible = passed == len(GATE_IDS)
    if (receipt.get("launch_decision") == "production_promotion_eligible") != eligible:
        raise LaunchProofControlError("launch decision contradicts gate status")
    if any(
        receipt.get(field) is not False
        for field in (
            "automatic_publish_enabled",
            "automatic_spend_enabled",
            "automatic_strategy_mutation_enabled",
            "top1_claim_allowed",
        )
    ):
        raise LaunchProofControlError("launch proof grants forbidden automatic authority")


__all__ = [
    "GATE_IDS",
    "LaunchProofControlError",
    "SCHEMA",
    "compile_launch_proof_control",
    "validate_launch_proof_control",
]
