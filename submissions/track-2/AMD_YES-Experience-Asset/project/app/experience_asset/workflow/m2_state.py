"""Minimal persisted LangGraph state for the E3/M2 production workflow."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, TypedDict

from pydantic import Field

from app.experience_asset.domain.models import ContractModel, Sha256

M2_WORKFLOW_VERSION = "experience-asset/e3-m2/v1"

M2_GRAPH_NODES = (
    "load_m2_context",
    "plan_m2_refinement",
    "persist_m2_map",
    "verify_m2_map",
    "terminalize_m2_run",
)

M2_GRAPH_EDGES = (
    ("START", "load_m2_context"),
    ("load_m2_context:ready", "plan_m2_refinement"),
    ("load_m2_context:stale_or_incompatible", "terminalize_m2_run"),
    ("plan_m2_refinement:planned", "persist_m2_map"),
    ("plan_m2_refinement:safe_failure", "terminalize_m2_run"),
    ("persist_m2_map:persisted", "verify_m2_map"),
    ("persist_m2_map:safe_failure", "terminalize_m2_run"),
    ("verify_m2_map:verified", "terminalize_m2_run"),
    ("verify_m2_map:safe_failure", "terminalize_m2_run"),
    ("terminalize_m2_run", "END"),
)

M2_TOPOLOGY_HASH = hashlib.sha256(
    json.dumps(
        {"nodes": M2_GRAPH_NODES, "edges": M2_GRAPH_EDGES},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()

M2_GRAPH_STATE_ALLOWED_KEYS = frozenset(
    {
        "run_id",
        "asset_id",
        "base_version_id",
        "command_id",
        "workflow_version",
        "topology_hash",
        "node_attempt",
        "last_node",
        "selected_edge",
        "semantic_role_proposal_hash",
        "model_call_count",
        "artifact_id",
        "canonical_version_id",
        "terminal_candidate",
        "finding_codes",
        "safe_message",
        "retryable",
    }
)


class M2GraphState(TypedDict):
    """Identifiers and sanitized outcomes only; canonical content is forbidden."""

    run_id: str
    asset_id: str
    base_version_id: str
    command_id: str
    workflow_version: str
    topology_hash: str
    node_attempt: int
    last_node: str
    selected_edge: str
    semantic_role_proposal_hash: str | None
    model_call_count: int
    artifact_id: str
    canonical_version_id: str
    terminal_candidate: str
    finding_codes: list[str]
    safe_message: str
    retryable: bool


class M2GraphStateV1(ContractModel):
    """Strict validator used at every E3 graph boundary."""

    run_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    base_version_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    workflow_version: Literal["experience-asset/e3-m2/v1"] = M2_WORKFLOW_VERSION
    topology_hash: Sha256 = M2_TOPOLOGY_HASH
    node_attempt: int = Field(ge=0)
    last_node: str = ""
    selected_edge: str = ""
    semantic_role_proposal_hash: Sha256 | None = None
    model_call_count: int = Field(default=0, ge=0, le=1)
    artifact_id: str = ""
    canonical_version_id: str = ""
    terminal_candidate: str = ""
    finding_codes: list[str] = Field(default_factory=list)
    safe_message: str = ""
    retryable: bool = False

    def as_graph_state(self) -> M2GraphState:
        return M2GraphState(**self.model_dump(mode="python"))


def validate_m2_graph_state(state: M2GraphState) -> M2GraphStateV1:
    """Fail closed if a checkpoint contains content outside the allowlist."""

    unknown = set(state) - M2_GRAPH_STATE_ALLOWED_KEYS
    if unknown:
        raise ValueError(f"M2 graph state contains forbidden fields: {sorted(unknown)}")
    return M2GraphStateV1.model_validate(state)
