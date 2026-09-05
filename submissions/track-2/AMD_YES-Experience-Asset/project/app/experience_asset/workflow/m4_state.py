"""LangGraph cursor contract for the E5/M4 workflow.

The cursor holds identifiers, bounded counters and sanitized outcomes only. Map
content never enters it: a checkpoint is replayed after a restart, and a cursor
carrying lesson text would let a resumed run re-persist content the user has
since corrected, with no signal that it came from a stale copy.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, TypedDict

from pydantic import Field, model_validator

from app.experience_asset.domain.models import ContractModel, Sha256

M4_WORKFLOW_VERSION = "experience-asset/e5-m4/v1"
M4_STRUCTURED_REPAIR_BUDGET = 2
M4_NODE_RETRY_BUDGET = 1
M4_REPLAN_BUDGET = 1
M4_MODEL_CALL_BUDGET = 4

M4_GRAPH_NODES = (
    "load_m4_context",
    "plan_m4_insights",
    "validate_m4_output",
    "repair_m4_output",
    "evaluate_m4_tool_policy",
    "persist_m4_map",
    "verify_m4_map",
    "replan_m4_run",
    "terminalize_m4_run",
)

M4_GRAPH_EDGES = (
    ("START", "load_m4_context"),
    ("load_m4_context:ready", "plan_m4_insights"),
    ("load_m4_context:stale_or_incompatible", "terminalize_m4_run"),
    ("plan_m4_insights:proposal_ready", "validate_m4_output"),
    ("plan_m4_insights:invalid_output", "repair_m4_output"),
    ("plan_m4_insights:safe_failure", "terminalize_m4_run"),
    ("validate_m4_output:valid", "evaluate_m4_tool_policy"),
    ("validate_m4_output:repairable", "repair_m4_output"),
    ("validate_m4_output:exhausted", "replan_m4_run"),
    ("repair_m4_output:repaired", "validate_m4_output"),
    ("repair_m4_output:retry_repair", "repair_m4_output"),
    ("repair_m4_output:exhausted", "replan_m4_run"),
    ("repair_m4_output:safe_failure", "terminalize_m4_run"),
    ("evaluate_m4_tool_policy:allow_or_no_tool", "persist_m4_map"),
    ("evaluate_m4_tool_policy:deny_or_invalid", "terminalize_m4_run"),
    ("persist_m4_map:persisted", "verify_m4_map"),
    ("persist_m4_map:safe_failure", "replan_m4_run"),
    ("verify_m4_map:verified", "terminalize_m4_run"),
    ("verify_m4_map:needs_replan", "replan_m4_run"),
    ("verify_m4_map:safe_failure", "terminalize_m4_run"),
    ("replan_m4_run:replanned", "plan_m4_insights"),
    ("replan_m4_run:exhausted", "terminalize_m4_run"),
    ("terminalize_m4_run", "END"),
)

M4_TOPOLOGY_HASH = hashlib.sha256(
    json.dumps(
        {"nodes": M4_GRAPH_NODES, "edges": M4_GRAPH_EDGES},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()

M4_GRAPH_STATE_ALLOWED_KEYS = frozenset(
    {
        "run_id",
        "asset_id",
        "base_version_id",
        "base_m3_artifact_id",
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


class M4GraphState(TypedDict):
    """References, bounded counters and sanitized outcomes only."""

    run_id: str
    asset_id: str
    base_version_id: str
    base_m3_artifact_id: str
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


class M4GraphStateV1(ContractModel):
    """Strict checkpoint validator; canonical/private content is forbidden."""

    run_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    base_version_id: str = Field(min_length=1)
    base_m3_artifact_id: str = Field(min_length=1)
    regenerate: bool = False
    expected_invalidated_artifact_id: str | None = None
    command_id: str = Field(min_length=1)
    workflow_version: Literal["experience-asset/e5-m4/v1"] = M4_WORKFLOW_VERSION
    topology_hash: Sha256 = M4_TOPOLOGY_HASH
    node_attempt: int = Field(ge=0, le=M4_NODE_RETRY_BUDGET)
    structured_repair_attempts: int = Field(default=0, ge=0, le=M4_STRUCTURED_REPAIR_BUDGET)
    replan_attempts: int = Field(default=0, ge=0, le=M4_REPLAN_BUDGET)
    model_call_count: int = Field(default=0, ge=0, le=M4_MODEL_CALL_BUDGET)
    last_node: str = ""
    selected_edge: str = ""
    structured_proposal_hash: Sha256 | None = None
    proposal_attempt: int = Field(default=0, ge=0, le=M4_MODEL_CALL_BUDGET)
    policy_decision_id: str | None = None
    tool_execution_id: str | None = None
    artifact_id: str | None = None
    canonical_version_id: str | None = None
    terminal_candidate: str = ""
    finding_codes: list[str] = Field(default_factory=list)
    safe_message: str = ""
    retryable: bool = False

    @model_validator(mode="after")
    def regeneration_identity_is_complete(self) -> M4GraphStateV1:
        if self.regenerate != (self.expected_invalidated_artifact_id is not None):
            raise ValueError("M4 regeneration mode requires its invalidated artifact identity")
        return self

    @model_validator(mode="after")
    def repair_attempts_require_model_calls(self) -> M4GraphStateV1:
        minimum_calls = self.structured_repair_attempts + self.replan_attempts
        if self.model_call_count < minimum_calls:
            raise ValueError("repair/re-plan attempts cannot exceed model-call evidence")
        return self

    def as_graph_state(self) -> M4GraphState:
        return M4GraphState(**self.model_dump(mode="python"))


def validate_m4_graph_state(state: M4GraphState) -> M4GraphStateV1:
    """Fail closed if a checkpoint contains content outside the allowlist."""

    unknown = set(state) - M4_GRAPH_STATE_ALLOWED_KEYS
    if unknown:
        raise ValueError(f"M4 graph state contains forbidden fields: {sorted(unknown)}")
    return M4GraphStateV1.model_validate(state)
