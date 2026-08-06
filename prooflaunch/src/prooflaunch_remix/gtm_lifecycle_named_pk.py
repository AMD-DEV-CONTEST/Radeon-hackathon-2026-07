from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


CONFIG_SCHEMA = "ProofLaunchCodexGTMLifecycleSuperChallengerDraftV1"
OUTPUT_SCHEMA = "ProofLaunchGTMLifecycleNamedPKSuperChallengerV1"
EXPECTED_PRODUCTS = (
    "Adobe Journey Optimizer", "Braze", "HubSpot", "Salesforce Marketing Cloud", "Iterable",
    "Customer.io", "Klaviyo", "Hightouch", "Clay", "Apollo",
)
EXPECTED_PROJECTS = {"pydantic_ai", "temporal", "dspy", "posthog", "growthbook", "meridian", "openlineage"}


class GTMLifecycleNamedPKError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def compile_lifecycle(config: Mapping[str, Any], *, bindings: list[dict[str, Any]]) -> dict[str, Any]:
    if config.get("schema") != CONFIG_SCHEMA:
        raise GTMLifecycleNamedPKError("lifecycle config schema drifted")
    roles = config.get("team_cells")
    nodes = config.get("graph_nodes")
    stress = config.get("opponent_stress_tests")
    oss = config.get("open_source_modifications")
    if not isinstance(roles, list) or not 8 <= len(roles) <= 16 or len({row.get("role") for row in roles}) != len(roles):
        raise GTMLifecycleNamedPKError("eight to sixteen distinct human capability cells are required")
    if not isinstance(nodes, list) or len(nodes) != 10 or [row.get("id") for row in nodes] != [f"N{i:02d}_{name}" for i, name in enumerate(("intake", "evidence", "strategy", "creation", "transcreation", "orchestration", "release", "observe", "decide", "learn"), 1)]:
        raise GTMLifecycleNamedPKError("ten-node lifecycle graph drifted")
    if not isinstance(stress, Mapping) or tuple(stress) != EXPECTED_PRODUCTS:
        raise GTMLifecycleNamedPKError("ten named lifecycle stress tests are required")
    if not isinstance(oss, list) or {row.get("project_id") for row in oss if isinstance(row, Mapping)} != EXPECTED_PROJECTS:
        raise GTMLifecycleNamedPKError("lifecycle open-source modification set drifted")
    if len(bindings) < 3 or any(not row.get("sha256") or not row.get("bytes") for row in bindings):
        raise GTMLifecycleNamedPKError("real candidate bindings are incomplete")
    harness = config.get("harness", {})
    if "automatic publication" not in harness.get("blocked", []) or "automatic spend" not in harness.get("blocked", []):
        raise GTMLifecycleNamedPKError("lifecycle harness escaped authority")
    payload = {
        "schema": OUTPUT_SCHEMA,
        "diagnosis": config["mission"],
        "strategy_binding": next(row for row in bindings if row["role"] == "strategy_and_creative"),
        "asset_bindings": [row for row in bindings if row["role"] != "strategy_and_creative"],
        "approval_receipt": {"status": "pending_named_human_content_bound_approval", "external_publish": False, "automatic_spend": False},
        "experiment_observation": {"class": "not_observed", "production_outcome": False, "causal_claim_allowed": False, "metrics": None},
        "next_cycle_recommendation": {"decision": "await_human_review_and_real_observation", "automatic_strategy_mutation": False, "human_application_required": True},
        "cross_device_memory": {"write_status": "not_authorized", "automatic_strategy_mutation": False, "exact_deletion_required": True},
        "team_cells": [dict(row) for row in roles],
        "graph": {"node_count": 10, "nodes": [dict(row) for row in nodes]},
        "loop_contract": "Each node may iterate only inside its typed acceptance contract; exhaustion returns a located failure to the deterministic Graph.",
        "harness": dict(harness),
        "okr": dict(config["okr"]),
        "opponent_stress_tests": dict(stress),
        "open_source_modifications": [dict(row) for row in oss],
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "release_eligible": False,
        "external_action_executed": False,
        "truth_boundary": config["truth_boundary"],
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_lifecycle(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != OUTPUT_SCHEMA or supplied != _digest(unsigned):
        raise GTMLifecycleNamedPKError("lifecycle seal is invalid")
    if payload.get("completed_named_product_pk_count") != 0 or payload.get("candidate_win_count") != 0 or payload.get("release_eligible") is not False or payload.get("external_action_executed") is not False:
        raise GTMLifecycleNamedPKError("lifecycle truth boundary drifted")
    if payload.get("experiment_observation", {}).get("production_outcome") is not False:
        raise GTMLifecycleNamedPKError("unobserved outcome was promoted")


__all__ = ["GTMLifecycleNamedPKError", "compile_lifecycle", "verify_lifecycle"]
