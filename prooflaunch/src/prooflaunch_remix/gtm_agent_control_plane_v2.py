from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


CONTROL_SCHEMA = "ProofLaunchGTMAgentControlPlaneV2"
RUN_SCHEMA = "ProofLaunchGTMCampaignReplayReceiptV2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GRAPH_NODES = ("diagnostic", "evidence", "strategy", "creative", "production", "adaptation", "review", "publishing", "measurement", "learning")
LOOP_ACTIONS = ("research", "generate", "critique", "compare", "repair")
AGENTS = ("strategy", "research", "culture", "copy", "creative", "industry", "media", "seo_geo", "lifecycle", "analytics")
ARTIFACT_TYPES = ("brief", "evidence", "hypothesis", "script", "asset", "approval", "experiment", "result")
HIGH_RISK_ACTIONS = ("release", "publish", "outreach", "spend", "contract", "account_operation", "data_import")


class GTMAgentControlPlaneError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_agent_control_plane() -> dict[str, Any]:
    nodes = []
    for index, node in enumerate(GRAPH_NODES):
        nodes.append({
            "node_id": node,
            "depends_on": [] if index == 0 else [GRAPH_NODES[index - 1]],
            "loop": {
                "allowed_actions": list(LOOP_ACTIONS),
                "maximum_iterations": 2,
                "acceptance_condition": f"typed {node} artifact passes schema, evidence, authority and quality gates",
                "on_exhaustion": "emit_precise_blocker",
                "may_change_other_nodes": False,
            },
        })
    agent_cards = []
    node_by_agent = {
        "strategy": "strategy", "research": "evidence", "culture": "diagnostic", "copy": "creative",
        "creative": "creative", "industry": "review", "media": "adaptation", "seo_geo": "adaptation",
        "lifecycle": "publishing", "analytics": "measurement",
    }
    for agent in AGENTS:
        agent_cards.append({
            "agent_id": agent,
            "assigned_node": node_by_agent[agent],
            "inputs": ["typed upstream artifacts", "source receipts", "brief authority envelope"],
            "outputs": [f"typed {agent} artifact", "findings", "precise blockers"],
            "tools": ["approved read-only research", "local deterministic validators", "authorized model gateway"],
            "decision_authority": "draft_compare_repair_inside_assigned_node",
            "prohibited_actions": list(HIGH_RISK_ACTIONS) + ["unapproved_memory_promotion"],
            "escalation_condition": "missing evidence, source conflict, policy risk, budget impact, or acceptance failure",
        })
    payload = {
        "schema": CONTROL_SCHEMA,
        "graph": {"nodes": nodes, "fixed_business_flow": True},
        "agents": agent_cards,
        "adversarial_review_required_for": ["strategy", "core_concept", "major_claim", "regulated_content", "major_budget"],
        "artifact_graph": {
            "types": list(ARTIFACT_TYPES),
            "required_fields": ["artifact_id", "artifact_type", "content_sha256", "parent_artifact_ids", "created_by", "created_at"],
            "parent_hash_chain_required": True,
        },
        "harness": {
            "required_controls": ["field_validation", "source_validation", "permission", "privacy", "budget", "frequency", "platform_rules", "audit", "circuit_breaker"],
            "fail_closed": True,
            "idempotency_required": True,
            "maximum_loop_iterations": 2,
            "automatic_publish_send_spend_contract_account_or_import": False,
            "human_authorization_required_for": list(HIGH_RISK_ACTIONS),
            "generic_copy_on_missing_dependency_allowed": False,
        },
        "blocker_contract": {
            "required_fields": ["blocker_code", "node_id", "missing_object", "required_action", "evidence_refs"],
            "generic_copy_fallback_allowed": False,
        },
        "replay_contract": {
            "node_sequence_required": list(GRAPH_NODES),
            "model_tool_human_decision_receipts_required": True,
            "content_addressed_artifact_graph_required": True,
        },
        "truth_boundary": "The control plane proves bounded workflow, authority and replay structure. It does not prove agent intelligence, creative quality, publication, or market effect.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_agent_control_plane(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != CONTROL_SCHEMA or supplied != _digest(unsigned):
        raise GTMAgentControlPlaneError("control-plane seal is invalid")
    nodes = payload.get("graph", {}).get("nodes", [])
    if [row.get("node_id") for row in nodes] != list(GRAPH_NODES):
        raise GTMAgentControlPlaneError("ten-node graph drifted")
    if any(tuple(row.get("loop", {}).get("allowed_actions", [])) != LOOP_ACTIONS or row.get("loop", {}).get("maximum_iterations") != 2 for row in nodes):
        raise GTMAgentControlPlaneError("node loop contract drifted")
    if {row.get("agent_id") for row in payload.get("agents", [])} != set(AGENTS):
        raise GTMAgentControlPlaneError("ten specialist agents are required")
    harness = payload.get("harness", {})
    if harness.get("automatic_publish_send_spend_contract_account_or_import") is not False or harness.get("generic_copy_on_missing_dependency_allowed") is not False:
        raise GTMAgentControlPlaneError("harness escaped authority or blocker boundary")


def _blocker(code: str, node: str, missing: str, action: str, refs: Sequence[str] = ()) -> dict[str, Any]:
    return {"blocker_code": code, "node_id": node, "missing_object": missing, "required_action": action, "evidence_refs": list(refs), "generic_copy_fallback_allowed": False}


def compile_campaign_replay_receipt(control: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, Any]:
    verify_agent_control_plane(control)
    run_id = str(run.get("run_id") or "")
    if not run_id:
        raise GTMAgentControlPlaneError("run_id is required")
    artifacts = run.get("artifacts") if isinstance(run.get("artifacts"), list) else []
    artifact_ids: set[str] = set()
    type_counts = {artifact_type: 0 for artifact_type in ARTIFACT_TYPES}
    blockers = []
    normalized_artifacts = []
    for artifact in artifacts:
        artifact_id = str(artifact.get("artifact_id") or "")
        artifact_type = str(artifact.get("artifact_type") or "")
        digest = str(artifact.get("content_sha256") or "")
        parents = [str(value) for value in artifact.get("parent_artifact_ids") or []]
        if not artifact_id or artifact_id in artifact_ids or artifact_type not in ARTIFACT_TYPES or not SHA256_RE.fullmatch(digest):
            raise GTMAgentControlPlaneError("artifact identity, type, or content hash is invalid")
        if not set(parents).issubset(artifact_ids):
            raise GTMAgentControlPlaneError("artifact graph parent is absent or appears after its child")
        artifact_ids.add(artifact_id); type_counts[artifact_type] += 1
        normalized_artifacts.append({
            "artifact_id": artifact_id, "artifact_type": artifact_type, "content_sha256": digest,
            "parent_artifact_ids": parents, "created_by": str(artifact.get("created_by") or ""),
            "created_at": str(artifact.get("created_at") or ""),
        })
    for artifact_type, count in type_counts.items():
        if count == 0:
            blockers.append(_blocker(f"missing_{artifact_type}_artifact", GRAPH_NODES[min(ARTIFACT_TYPES.index(artifact_type), len(GRAPH_NODES) - 1)], artifact_type, f"Produce and seal a typed {artifact_type} artifact before continuing."))

    node_receipts = run.get("node_receipts") if isinstance(run.get("node_receipts"), list) else []
    if [row.get("node_id") for row in node_receipts] != list(GRAPH_NODES):
        blockers.append(_blocker("incomplete_node_replay", "learning", "ten ordered node receipts", "Record model, tool, and human decision receipts for every graph node."))
    else:
        for row in node_receipts:
            if not SHA256_RE.fullmatch(str(row.get("input_sha256") or "")) or not SHA256_RE.fullmatch(str(row.get("output_sha256") or "")) or not isinstance(row.get("tool_receipt_sha256s"), list) or not isinstance(row.get("human_decision_receipt_sha256s"), list):
                blockers.append(_blocker("incomplete_node_receipt", str(row.get("node_id")), "input/output/tool/human receipt binding", "Seal the missing node receipt fields."))

    approvals = run.get("human_authorizations") if isinstance(run.get("human_authorizations"), list) else []
    for action in run.get("requested_high_risk_actions") or []:
        action_type = str(action.get("action_type") or "")
        object_hash = str(action.get("object_sha256") or "")
        matching = [approval for approval in approvals if approval.get("action_type") == action_type and approval.get("object_sha256") == object_hash and len(str(approval.get("approver_name") or "").strip()) >= 3]
        if action_type not in HIGH_RISK_ACTIONS or not SHA256_RE.fullmatch(object_hash) or not matching:
            blockers.append(_blocker("missing_high_risk_authorization", "publishing", f"named authorization for {action_type or 'unknown action'}", "Obtain a named, object-hash-bound human authorization.", [object_hash] if object_hash else []))
    payload = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "control_plane_sha256": control["content_sha256"],
        "artifacts": normalized_artifacts,
        "node_receipts": node_receipts,
        "human_authorizations": approvals,
        "blockers": blockers,
        "status": "replayable_prepared_run" if not blockers else "blocked_with_precise_dependencies",
        "external_action_executed": False,
        "automatic_memory_promotion_executed": False,
        "truth_boundary": "The receipt replays declared artifacts, tools, models and human decisions. It does not prove an external action or result occurred.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_campaign_replay_receipt(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != RUN_SCHEMA or supplied != _digest(unsigned):
        raise GTMAgentControlPlaneError("campaign replay seal is invalid")
    if payload.get("external_action_executed") is not False or payload.get("automatic_memory_promotion_executed") is not False:
        raise GTMAgentControlPlaneError("campaign replay overstates external or learning action")
    if any(blocker.get("generic_copy_fallback_allowed") is not False for blocker in payload.get("blockers", [])):
        raise GTMAgentControlPlaneError("a blocker permits generic-copy fallback")


__all__ = ["GTMAgentControlPlaneError", "build_agent_control_plane", "compile_campaign_replay_receipt", "verify_agent_control_plane", "verify_campaign_replay_receipt"]
