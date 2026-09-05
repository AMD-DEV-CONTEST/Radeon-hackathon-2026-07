"""Isolated M5 LangGraph topology and checkpoint-state proposal.

This freezes the E6 orchestration boundary without wiring the production graph
or persisting canonical/private content. E5 integration supplies the real
context loader and repositories later.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, TypedDict

from pydantic import Field, model_validator

from app.experience_asset.domain.models import ContractModel, Sha256

from .contracts import M5_WORKFLOW_IDENTITY

M5_WORKFLOW_VERSION = M5_WORKFLOW_IDENTITY
M5_NODE_RETRY_BUDGET = 1
M5_PRIVACY_PROPOSAL_BUDGET = 1
M5_REEVALUATION_BUDGET = 2

M5_GRAPH_NODES = (
    "load_m5_context",
    "evaluate_m5_routes",
    "review_m5_privacy",
    "wait_m5_privacy_resolution",
    "apply_m5_privacy_resolution",
    "recompose_m5_context",
    "wait_m5_approval",
    "validate_m5_approval",
    "verify_m5_state",
    "terminalize_m5_run",
)

M5_GRAPH_EDGES = (
    ("START", "load_m5_context"),
    ("load_m5_context:ready", "evaluate_m5_routes"),
    ("load_m5_context:not_ready_or_stale", "terminalize_m5_run"),
    ("evaluate_m5_routes:evaluated", "review_m5_privacy"),
    ("evaluate_m5_routes:safe_failure", "terminalize_m5_run"),
    ("review_m5_privacy:open_findings", "wait_m5_privacy_resolution"),
    ("review_m5_privacy:resolved_or_empty", "wait_m5_approval"),
    ("review_m5_privacy:safe_failure", "terminalize_m5_run"),
    ("wait_m5_privacy_resolution:user_action", "apply_m5_privacy_resolution"),
    ("wait_m5_privacy_resolution:pause", "terminalize_m5_run"),
    ("apply_m5_privacy_resolution:recorded", "evaluate_m5_routes"),
    ("apply_m5_privacy_resolution:canonical_change", "recompose_m5_context"),
    ("apply_m5_privacy_resolution:denied", "terminalize_m5_run"),
    ("recompose_m5_context:current", "evaluate_m5_routes"),
    ("recompose_m5_context:stale_or_exhausted", "terminalize_m5_run"),
    ("wait_m5_approval:no_final_draft", "verify_m5_state"),
    ("wait_m5_approval:explicit_action", "validate_m5_approval"),
    ("wait_m5_approval:pause", "terminalize_m5_run"),
    ("validate_m5_approval:valid", "verify_m5_state"),
    ("validate_m5_approval:denied_or_stale", "terminalize_m5_run"),
    ("verify_m5_state:verified", "terminalize_m5_run"),
    ("verify_m5_state:safe_failure", "terminalize_m5_run"),
    ("terminalize_m5_run", "END"),
)

M5_TOPOLOGY_HASH = hashlib.sha256(
    json.dumps(
        {"nodes": M5_GRAPH_NODES, "edges": M5_GRAPH_EDGES},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()

M5_GRAPH_STATE_ALLOWED_KEYS = frozenset(
    {
        "run_id",
        "asset_id",
        "base_version_id",
        "command_id",
        "content_hash",
        "relation_projection_hash",
        "workflow_version",
        "topology_hash",
        "node_attempt",
        "privacy_proposal_attempts",
        "reevaluation_count",
        "last_node",
        "selected_edge",
        "route_matrix_hash",
        "privacy_review_hash",
        "route_draft_binding_hash",
        "approval_id",
        "canonical_version_id",
        "wait_reason",
        "terminal_candidate",
        "finding_codes",
        "safe_message",
        "retryable",
    }
)


class M5GraphState(TypedDict):
    """Bounded IDs, hashes, counters, and sanitized outcomes only."""

    run_id: str
    asset_id: str
    base_version_id: str
    command_id: str
    content_hash: str
    relation_projection_hash: str
    workflow_version: str
    topology_hash: str
    node_attempt: int
    privacy_proposal_attempts: int
    reevaluation_count: int
    last_node: str
    selected_edge: str
    route_matrix_hash: str | None
    privacy_review_hash: str | None
    route_draft_binding_hash: str | None
    approval_id: str | None
    canonical_version_id: str | None
    wait_reason: str
    terminal_candidate: str
    finding_codes: list[str]
    safe_message: str
    retryable: bool


class M5GraphStateV1(ContractModel):
    """Strict M5 checkpoint validator; raw product content is forbidden."""

    run_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    base_version_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    content_hash: Sha256
    relation_projection_hash: Sha256
    workflow_version: Literal["experience-asset/e6-m5-isolated/v1"] = M5_WORKFLOW_VERSION
    topology_hash: Sha256 = M5_TOPOLOGY_HASH
    node_attempt: int = Field(default=0, ge=0, le=M5_NODE_RETRY_BUDGET)
    privacy_proposal_attempts: int = Field(
        default=0,
        ge=0,
        le=M5_PRIVACY_PROPOSAL_BUDGET,
    )
    reevaluation_count: int = Field(default=0, ge=0, le=M5_REEVALUATION_BUDGET)
    last_node: str = ""
    selected_edge: str = ""
    route_matrix_hash: Sha256 | None = None
    privacy_review_hash: Sha256 | None = None
    route_draft_binding_hash: Sha256 | None = None
    approval_id: str | None = None
    canonical_version_id: str | None = None
    wait_reason: str = ""
    terminal_candidate: str = ""
    finding_codes: list[str] = Field(default_factory=list)
    safe_message: str = ""
    retryable: bool = False

    @model_validator(mode="after")
    def approval_identity_is_complete(self) -> M5GraphStateV1:
        if self.approval_id is not None and (
            self.route_draft_binding_hash is None or self.privacy_review_hash is None
        ):
            raise ValueError("approval checkpoint requires draft and privacy binding hashes")
        return self

    def as_graph_state(self) -> M5GraphState:
        return M5GraphState(**self.model_dump(mode="python"))


def validate_m5_graph_state(state: M5GraphState) -> M5GraphStateV1:
    """Reject raw/private/browser authority fields before checkpointing."""

    unknown = set(state) - M5_GRAPH_STATE_ALLOWED_KEYS
    if unknown:
        raise ValueError(f"M5 graph state contains forbidden fields: {sorted(unknown)}")
    return M5GraphStateV1.model_validate(state)


__all__ = [
    "M5_GRAPH_EDGES",
    "M5_GRAPH_NODES",
    "M5_GRAPH_STATE_ALLOWED_KEYS",
    "M5_NODE_RETRY_BUDGET",
    "M5_PRIVACY_PROPOSAL_BUDGET",
    "M5_REEVALUATION_BUDGET",
    "M5_TOPOLOGY_HASH",
    "M5_WORKFLOW_VERSION",
    "M5GraphState",
    "M5GraphStateV1",
    "validate_m5_graph_state",
]
