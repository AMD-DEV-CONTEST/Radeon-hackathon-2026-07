"""Proposed minimal LangGraph cursor contract for the E4/M3 workflow."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, TypedDict

from pydantic import Field, model_validator

from app.experience_asset.domain.models import ContractModel, Sha256

M3_WORKFLOW_VERSION = "experience-asset/e4-m3/v1"
M3_STRUCTURED_REPAIR_BUDGET = 2
M3_NODE_RETRY_BUDGET = 1
M3_REPLAN_BUDGET = 1
M3_MODEL_CALL_BUDGET = 4

M3_GRAPH_NODES = (
    "load_m3_context",
    "plan_m3_ledger",
    "validate_m3_output",
    "repair_m3_output",
    "evaluate_m3_tool_policy",
    "persist_m3_ledger",
    "verify_m3_ledger",
    "replan_m3_run",
    "terminalize_m3_run",
)

M3_GRAPH_EDGES = (
    ("START", "load_m3_context"),
    ("load_m3_context:ready", "plan_m3_ledger"),
    ("load_m3_context:stale_or_incompatible", "terminalize_m3_run"),
    ("plan_m3_ledger:proposal_ready", "validate_m3_output"),
    ("plan_m3_ledger:invalid_output", "repair_m3_output"),
    ("plan_m3_ledger:safe_failure", "terminalize_m3_run"),
    ("validate_m3_output:valid", "evaluate_m3_tool_policy"),
    ("validate_m3_output:repairable", "repair_m3_output"),
    ("validate_m3_output:exhausted", "replan_m3_run"),
    ("repair_m3_output:repaired", "validate_m3_output"),
    ("repair_m3_output:retry_repair", "repair_m3_output"),
    ("repair_m3_output:exhausted", "replan_m3_run"),
    ("repair_m3_output:safe_failure", "terminalize_m3_run"),
    ("evaluate_m3_tool_policy:allow_or_no_tool", "persist_m3_ledger"),
    ("evaluate_m3_tool_policy:deny_or_invalid", "terminalize_m3_run"),
    ("persist_m3_ledger:persisted", "verify_m3_ledger"),
    ("persist_m3_ledger:safe_failure", "replan_m3_run"),
    ("verify_m3_ledger:verified", "terminalize_m3_run"),
    ("verify_m3_ledger:needs_replan", "replan_m3_run"),
    ("verify_m3_ledger:safe_failure", "terminalize_m3_run"),
    ("replan_m3_run:replanned", "plan_m3_ledger"),
    ("replan_m3_run:exhausted", "terminalize_m3_run"),
    ("terminalize_m3_run", "END"),
)

M3_TOPOLOGY_HASH = hashlib.sha256(
    json.dumps(
        {"nodes": M3_GRAPH_NODES, "edges": M3_GRAPH_EDGES},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()

M3_GRAPH_STATE_ALLOWED_KEYS = frozenset(
    {
        "run_id",
        "asset_id",
        "base_version_id",
        "base_m2_artifact_id",
        "regenerate",
        "expected_invalidated_artifact_id",
        "command_id",
        "workflow_version",
        "topology_hash",
        "node_attempt",
        "structured_repair_attempts",
        "replan_attempts",
        "model_call_count",
        "last_node",
        "selected_edge",
        "structured_proposal_hash",
        "proposal_attempt",
        "policy_decision_id",
        "tool_execution_id",
        "artifact_id",
        "canonical_version_id",
        "terminal_candidate",
        "finding_codes",
        "safe_message",
        "retryable",
    }
)


class M3GraphState(TypedDict):
    """References, bounded counters and sanitized outcomes only."""

    run_id: str
    asset_id: str
    base_version_id: str
    base_m2_artifact_id: str
    regenerate: bool
    expected_invalidated_artifact_id: str | None
    command_id: str
    workflow_version: str
    topology_hash: str
    node_attempt: int
    structured_repair_attempts: int
    replan_attempts: int
    model_call_count: int
    last_node: str
    selected_edge: str
    structured_proposal_hash: str | None
    proposal_attempt: int
    policy_decision_id: str | None
    tool_execution_id: str | None
    artifact_id: str | None
    canonical_version_id: str | None
    terminal_candidate: str
    finding_codes: list[str]
    safe_message: str
    retryable: bool


class M3GraphStateV1(ContractModel):
    """Strict checkpoint validator; canonical/private content is forbidden."""

    run_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    base_version_id: str = Field(min_length=1)
    base_m2_artifact_id: str = Field(min_length=1)
    regenerate: bool = False
    expected_invalidated_artifact_id: str | None = None
    command_id: str = Field(min_length=1)
    workflow_version: Literal["experience-asset/e4-m3/v1"] = M3_WORKFLOW_VERSION
    topology_hash: Sha256 = M3_TOPOLOGY_HASH
    node_attempt: int = Field(ge=0, le=M3_NODE_RETRY_BUDGET)
    structured_repair_attempts: int = Field(default=0, ge=0, le=M3_STRUCTURED_REPAIR_BUDGET)
    replan_attempts: int = Field(default=0, ge=0, le=M3_REPLAN_BUDGET)
    model_call_count: int = Field(default=0, ge=0, le=M3_MODEL_CALL_BUDGET)
    last_node: str = ""
    selected_edge: str = ""
    structured_proposal_hash: Sha256 | None = None
    proposal_attempt: int = Field(default=0, ge=0, le=M3_MODEL_CALL_BUDGET)
    policy_decision_id: str | None = None
    tool_execution_id: str | None = None
    artifact_id: str | None = None
    canonical_version_id: str | None = None
    terminal_candidate: str = ""
    finding_codes: list[str] = Field(default_factory=list)
    safe_message: str = ""
    retryable: bool = False

    @model_validator(mode="after")
    def regeneration_identity_is_complete(self) -> M3GraphStateV1:
        if self.regenerate != (self.expected_invalidated_artifact_id is not None):
            raise ValueError("M3 regeneration mode requires its invalidated artifact identity")
        return self

    @model_validator(mode="after")
    def repair_attempts_require_model_calls(self) -> M3GraphStateV1:
        minimum_calls = self.structured_repair_attempts + self.replan_attempts
        if self.model_call_count < minimum_calls:
            raise ValueError("repair/re-plan attempts cannot exceed model-call evidence")
        return self

    def as_graph_state(self) -> M3GraphState:
        return M3GraphState(**self.model_dump(mode="python"))


def validate_m3_graph_state(state: M3GraphState) -> M3GraphStateV1:
    """Fail closed if a checkpoint contains content outside the allowlist."""

    unknown = set(state) - M3_GRAPH_STATE_ALLOWED_KEYS
    if unknown:
        raise ValueError(f"M3 graph state contains forbidden fields: {sorted(unknown)}")
    return M3GraphStateV1.model_validate(state)
