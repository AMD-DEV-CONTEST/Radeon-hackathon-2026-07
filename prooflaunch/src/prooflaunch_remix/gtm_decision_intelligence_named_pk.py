from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


CONFIG_SCHEMA = "ProofLaunchCodexDecisionIntelligenceSuperChallengersDraftV1"
MEMO_SCHEMA = "ProofLaunchDataStrategyNamedPKSuperChallengerV1"
MEASUREMENT_SCHEMA = "ProofLaunchMarketingAnalyticsNamedPKSuperChallengerV1"


class DecisionIntelligenceNamedPKError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_sha256"] = _digest(result)
    return result


def compile_decision_intelligence(config: Mapping[str, Any], *, lineage: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    if config.get("schema") != CONFIG_SCHEMA:
        raise DecisionIntelligenceNamedPKError("decision intelligence schema drifted")
    memo = config.get("decision_memo")
    measurement = config.get("measurement_system")
    oss = config.get("open_source_modifications")
    if not isinstance(memo, Mapping) or not isinstance(measurement, Mapping) or not isinstance(oss, Mapping):
        raise DecisionIntelligenceNamedPKError("decision intelligence config is incomplete")
    if len(memo.get("scenarios", [])) != 5 or len(memo.get("opponent_stress_tests", {})) != 10:
        raise DecisionIntelligenceNamedPKError("data strategy coverage drifted")
    variables = memo.get("decision_variables", [])
    if next(row for row in variables if row.get("variable") == "source_hidden_human_reviews").get("current") != 0:
        raise DecisionIntelligenceNamedPKError("human review truth drifted")
    if next(row for row in variables if row.get("variable") == "production_qualified_actions").get("current", "missing") is not None:
        raise DecisionIntelligenceNamedPKError("unobserved production action must remain null")
    if len(measurement.get("event_contract", [])) != 6 or len(measurement.get("opponent_stress_tests", {})) != 10:
        raise DecisionIntelligenceNamedPKError("measurement coverage drifted")
    if measurement.get("incrementality", {}).get("causal_claim_allowed") is not False or measurement.get("primary_metric", {}).get("value", "missing") is not None:
        raise DecisionIntelligenceNamedPKError("unobserved measurement was promoted")
    if len(lineage) < 3 or any(not row.get("sha256") for row in lineage):
        raise DecisionIntelligenceNamedPKError("lineage is incomplete")
    common = {
        "campaign_id": config["campaign_id"],
        "lineage": lineage,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "external_action_executed": False,
        "truth_boundary": config["truth_boundary"],
    }
    memo_payload = _seal({
        "schema": MEMO_SCHEMA,
        **common,
        **dict(memo),
        "open_source_modifications": list(oss["data_strategy"]),
        "causal_claim_allowed": False,
    })
    measurement_payload = _seal({
        "schema": MEASUREMENT_SCHEMA,
        **common,
        **dict(measurement),
        "open_source_modifications": list(oss["marketing_analytics"]),
    })
    return memo_payload, measurement_payload


def verify(payload: Mapping[str, Any], schema: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != schema or supplied != _digest(unsigned):
        raise DecisionIntelligenceNamedPKError("decision intelligence seal is invalid")
    if payload.get("completed_named_product_pk_count") != 0 or payload.get("candidate_win_count") != 0 or payload.get("external_action_executed") is not False:
        raise DecisionIntelligenceNamedPKError("decision intelligence truth boundary drifted")


__all__ = ["DecisionIntelligenceNamedPKError", "MEMO_SCHEMA", "MEASUREMENT_SCHEMA", "compile_decision_intelligence", "verify"]
