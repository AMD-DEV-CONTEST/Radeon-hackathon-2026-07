"""Minimal persisted LangGraph state for the E2/M1 production workflow."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, TypedDict

from pydantic import Field

from app.experience_asset.domain.models import ContractModel, Sha256

WORKFLOW_VERSION = "experience-asset/e2-m1/v1"

M1_GRAPH_NODES = (
    "load_run_context",
    "plan_m1_action",
    "propose_current_source_call",
    "evaluate_runtime_policy",
    "execute_current_source_tool",
    "verify_run_result",
    "persist_run_outcome",
    "terminalize_run",
)

M1_GRAPH_EDGES = (
    ("START", "load_run_context"),
    ("load_run_context:ready", "plan_m1_action"),
    ("load_run_context:stale_or_incompatible", "persist_run_outcome"),
    ("plan_m1_action:planned", "propose_current_source_call"),
    ("plan_m1_action:safe_failure", "persist_run_outcome"),
    ("propose_current_source_call:proposal_ready", "evaluate_runtime_policy"),
    ("propose_current_source_call:model_or_format_failure", "persist_run_outcome"),
    ("evaluate_runtime_policy:allow", "execute_current_source_tool"),
    ("evaluate_runtime_policy:deny_or_invalid", "verify_run_result"),
    ("execute_current_source_tool:tool_recorded", "verify_run_result"),
    ("execute_current_source_tool:safe_failure", "persist_run_outcome"),
    ("verify_run_result", "persist_run_outcome"),
    ("persist_run_outcome", "terminalize_run"),
    ("terminalize_run", "END"),
)

TOPOLOGY_HASH = hashlib.sha256(
    json.dumps(
        {"nodes": M1_GRAPH_NODES, "edges": M1_GRAPH_EDGES},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()

GRAPH_STATE_ALLOWED_KEYS = frozenset(
    {
        "run_id",
        "asset_id",
        "base_version_id",
        "command_id",
        "workflow_version",
        "topology_hash",
        "projection_sequence",
        "node_attempt",
        "last_node",
        "selected_edge",
        "terminal_candidate",
    }
)


class M1GraphState(TypedDict):
    """LangGraph schema containing references and cursor metadata only."""

    run_id: str
    asset_id: str
    base_version_id: str
    command_id: str
    workflow_version: str
    topology_hash: str
    projection_sequence: int
    node_attempt: int
    last_node: str
    selected_edge: str
    terminal_candidate: str


class M1GraphStateV1(ContractModel):
    """Strict validator used at every production graph boundary."""

    run_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    base_version_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    workflow_version: Literal["experience-asset/e2-m1/v1"] = WORKFLOW_VERSION
    topology_hash: Sha256 = TOPOLOGY_HASH
    projection_sequence: int = Field(ge=-1)
    node_attempt: int = Field(ge=0)
    last_node: str = ""
    selected_edge: str = ""
    terminal_candidate: str = ""

    def as_graph_state(self) -> M1GraphState:
        return M1GraphState(**self.model_dump(mode="python"))


def validate_graph_state(state: M1GraphState) -> M1GraphStateV1:
    """Fail closed when a node or checkpoint introduces a non-allowlisted field."""

    unknown = set(state) - GRAPH_STATE_ALLOWED_KEYS
    if unknown:
        raise ValueError(f"graph state contains forbidden fields: {sorted(unknown)}")
    return M1GraphStateV1.model_validate(state)
