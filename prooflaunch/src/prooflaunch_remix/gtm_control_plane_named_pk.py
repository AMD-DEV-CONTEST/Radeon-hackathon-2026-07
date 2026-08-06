from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


CONFIG_SCHEMA = "ProofLaunchCodexControlPlaneSuperChallengersDraftV1"
MEMORY_SCHEMA = "ProofLaunchCrossDeviceMemoryNamedPKSuperChallengerV1"
AGENT_SCHEMA = "ProofLaunchEmployeeAgentNamedPKSuperChallengerV1"
AD_SCHEMA = "ProofLaunchAdvertisingNamedPKSuperChallengerV1"


class ControlPlaneNamedPKError(ValueError):
    pass


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_sha256"] = _digest(result)
    return result


def _common(config: Mapping[str, Any], lineage: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "campaign_id": config["campaign_id"],
        "frozen_brief": dict(config["frozen_brief"]),
        "lineage": lineage,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "external_action_executed": False,
        "production_effect_observed": False,
        "truth_boundary": config["truth_boundary"],
    }


def compile_control_plane(config: Mapping[str, Any], *, lineage: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if config.get("schema") != CONFIG_SCHEMA:
        raise ControlPlaneNamedPKError("control-plane schema drifted")
    brief = config.get("frozen_brief")
    memory = config.get("memory_system")
    agent = config.get("employee_agent")
    ads = config.get("advertising_system")
    oss = config.get("open_source_modifications")
    if not all(isinstance(row, Mapping) for row in (brief, memory, agent, ads, oss)):
        raise ControlPlaneNamedPKError("control-plane config is incomplete")
    if brief.get("external_activation_authorized") is not False or brief.get("budget_usd") != 0:
        raise ControlPlaneNamedPKError("brief authority drifted")
    if len(memory.get("retrieval_tests", [])) < 5 or len(memory.get("opponent_stress_tests", {})) != 10:
        raise ControlPlaneNamedPKError("memory execution coverage drifted")
    if len(agent.get("graph_nodes", [])) < 8 or len(agent.get("opponent_stress_tests", {})) != 10:
        raise ControlPlaneNamedPKError("agent execution coverage drifted")
    limits = agent.get("harness", {}).get("hard_limits", {})
    if limits.get("external_actions") != 0 or limits.get("paid_spend_usd") != 0:
        raise ControlPlaneNamedPKError("agent harness authority drifted")
    experiment = ads.get("experiment", {})
    if len(ads.get("creative_matrix", [])) < 3 or len(ads.get("channel_plans", [])) < 4 or len(ads.get("opponent_stress_tests", {})) != 10:
        raise ControlPlaneNamedPKError("advertising execution coverage drifted")
    if ads.get("activation_mode") != "inactive_review_only" or experiment.get("observed_incremental_lift", "missing") is not None:
        raise ControlPlaneNamedPKError("unobserved advertising outcome was promoted")
    if len(lineage) < 4 or any(not row.get("sha256") for row in lineage):
        raise ControlPlaneNamedPKError("lineage is incomplete")
    common = _common(config, lineage)
    memory_payload = _seal({"schema": MEMORY_SCHEMA, **common, **dict(memory), "open_source_modifications": list(oss["memory"])})
    agent_payload = _seal({"schema": AGENT_SCHEMA, **common, **dict(agent), "open_source_modifications": list(oss["agent"])})
    ad_payload = _seal({"schema": AD_SCHEMA, **common, **dict(ads), "open_source_modifications": list(oss["advertising"]), "paid_media_spend_usd": 0})
    return memory_payload, agent_payload, ad_payload


def verify(payload: Mapping[str, Any], schema: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != schema or supplied != _digest(unsigned):
        raise ControlPlaneNamedPKError("control-plane seal is invalid")
    if payload.get("candidate_win_count") != 0 or payload.get("completed_named_product_pk_count") != 0:
        raise ControlPlaneNamedPKError("named-product truth boundary drifted")
    if payload.get("external_action_executed") is not False or payload.get("production_effect_observed") is not False:
        raise ControlPlaneNamedPKError("external-effect truth boundary drifted")


__all__ = ["AD_SCHEMA", "AGENT_SCHEMA", "CONFIG_SCHEMA", "ControlPlaneNamedPKError", "MEMORY_SCHEMA", "compile_control_plane", "verify"]
