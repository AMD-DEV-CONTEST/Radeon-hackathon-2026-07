from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


SCHEMA = "ProofLaunchGTMPromotionGovernanceV1"


class PromotionGovernanceError(ValueError):
    """Quality promotion or rollback governance became unsafe or overstated."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def compile_promotion_governance(
    *,
    strategy_id: str,
    campaign_id: str,
    candidate_revision: str,
    stable_revision: str,
    g0_contract_passed: bool,
) -> dict[str, Any]:
    if not all(isinstance(value, str) and value.strip() for value in (strategy_id, campaign_id, candidate_revision, stable_revision)):
        raise PromotionGovernanceError("promotion identities must be nonblank")
    if not isinstance(g0_contract_passed, bool):
        raise PromotionGovernanceError("G0 status must be boolean")
    judges = [
        {
            "judge_id": "judge-hook",
            "single_axis": "hook成立",
            "binary_question": "Does the opening establish one specific audience tension or attention mechanism without unsupported certainty?",
            "positive_definition": "one legible tension/mechanism appears before explanation",
            "negative_definition": "generic opening, multiple competing hooks, or unsupported outcome certainty",
        },
        {
            "judge_id": "judge-platform-native",
            "single_axis": "平台原生",
            "binary_question": "Does the asset use the selected platform's native attention, interaction and formatting behavior?",
            "positive_definition": "format and interaction job are platform-specific",
            "negative_definition": "the same copy could be pasted unchanged across channels",
        },
        {
            "judge_id": "judge-evidence",
            "single_axis": "证据可信",
            "binary_question": "Is every factual claim bound to a valid source, digest, rights scope and named release decision?",
            "positive_definition": "claim-level provenance and release eligibility are intact",
            "negative_definition": "missing, expired, restricted, drifted or unapproved evidence",
        },
        {
            "judge_id": "judge-style",
            "single_axis": "风格一致",
            "binary_question": "Does the expression preserve the declared brand voice and avoid prohibited tactics?",
            "positive_definition": "voice and identity are coherent across copy and media direction",
            "negative_definition": "identity drift, generic AI cadence, inappropriate humor or prohibited tactic",
        },
        {
            "judge_id": "judge-direct-publishability",
            "single_axis": "可直接发布",
            "binary_question": "Can a named editor publish this unchanged except for cosmetic corrections?",
            "positive_definition": "no strategy, hook, proof, argument, shot or CTA rewrite is required",
            "negative_definition": "any structural rewrite, blocking defect or unresolved release gate remains",
        },
    ]
    for judge in judges:
        judge.update(
            {
                "output_schema": {"label": "pass_or_fail", "reason": "required", "evidence_span": "required"},
                "abstention_allowed": True,
                "human_calibration_label_count": 0,
                "tpr_observed": None,
                "tnr_observed": None,
                "calibration_gate_passed": False,
                "production_decision_allowed": False,
            }
        )
    gates = {
        "G0_contract": {
            "passed": g0_contract_passed,
            "evidence": "deterministic production contracts and mechanical quality receipts",
        },
        "G1_professional_editor": {
            "passed": False,
            "evidence": None,
        },
        "G2_same_brief_blind_preference": {
            "passed": False,
            "evidence": None,
        },
        "G3_observed_distribution_effect": {
            "passed": False,
            "evidence": None,
        },
    }
    promotion_allowed = all(gate["passed"] for gate in gates.values())
    regression_detected = not g0_contract_passed
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "strategy_id": strategy_id,
        "campaign_id": campaign_id,
        "single_axis_binary_judges": judges,
        "judge_count": len(judges),
        "judge_calibration_state": "unobserved_requires_at_least_100_human_labels_per_judge",
        "candidate_revision": candidate_revision,
        "stable_revision": stable_revision,
        "quality_gates": gates,
        "promotion_allowed": promotion_allowed,
        "promotion_executed": False,
        "regression_detected": regression_detected,
        "internal_rollback_policy": {
            "automatic_internal_alias_rollback_enabled": True,
            "trigger": "any required G0 regression after a previously sealed stable revision",
            "target": stable_revision,
            "current_decision": "reject_candidate_keep_stable" if regression_detected else "hold_candidate_pending_G1_G2_G3",
            "external_publish_send_or_spend_action_allowed": False,
            "rollback_execution_observed": False,
        },
        "automatic_model_or_strategy_promotion_enabled": False,
        "external_action_executed": False,
        "truth_boundary": (
            "Judge definitions and internal promotion rules are implemented, but no judge is calibrated and G1–G3 are unobserved. "
            "The candidate cannot be promoted, and no external publication, send or spend is affected."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_promotion_governance(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise PromotionGovernanceError("promotion governance seal is invalid")
    judges = payload.get("single_axis_binary_judges")
    if not isinstance(judges, list) or len(judges) != 5 or len({row.get("single_axis") for row in judges if isinstance(row, Mapping)}) != 5:
        raise PromotionGovernanceError("single-axis judge plan is incomplete")
    if any(row.get("production_decision_allowed") is not False for row in judges if isinstance(row, Mapping)):
        raise PromotionGovernanceError("uncalibrated judge entered production")
    gates = payload.get("quality_gates")
    if not isinstance(gates, Mapping) or set(gates) != {"G0_contract", "G1_professional_editor", "G2_same_brief_blind_preference", "G3_observed_distribution_effect"}:
        raise PromotionGovernanceError("G0-G3 promotion gates are incomplete")
    expected = all(isinstance(value, Mapping) and value.get("passed") is True for value in gates.values())
    if payload.get("promotion_allowed") is not expected:
        raise PromotionGovernanceError("promotion decision does not match G0-G3")
    if payload.get("automatic_model_or_strategy_promotion_enabled") is not False or payload.get("external_action_executed") is not False:
        raise PromotionGovernanceError("promotion governance enabled an unsafe action")
