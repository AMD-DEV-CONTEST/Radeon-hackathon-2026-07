from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.experience_asset.application.m5.workflow_contract import (
    M5_GRAPH_EDGES,
    M5_GRAPH_NODES,
    M5_GRAPH_STATE_ALLOWED_KEYS,
    M5_TOPOLOGY_HASH,
    M5_WORKFLOW_VERSION,
    M5GraphStateV1,
    validate_m5_graph_state,
)

ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "contracts" / "checkpoints" / "e6-m5-contract-fixtures-v1.json"


def valid_state() -> dict[str, object]:
    return {
        "run_id": str(uuid4()),
        "asset_id": str(uuid4()),
        "base_version_id": str(uuid4()),
        "command_id": str(uuid4()),
        "content_hash": "1" * 64,
        "relation_projection_hash": "2" * 64,
        "workflow_version": M5_WORKFLOW_VERSION,
        "topology_hash": M5_TOPOLOGY_HASH,
        "node_attempt": 0,
        "privacy_proposal_attempts": 0,
        "reevaluation_count": 0,
        "last_node": "",
        "selected_edge": "",
        "route_matrix_hash": None,
        "privacy_review_hash": None,
        "route_draft_binding_hash": None,
        "approval_id": None,
        "canonical_version_id": None,
        "wait_reason": "",
        "terminal_candidate": "",
        "finding_codes": [],
        "safe_message": "",
        "retryable": False,
    }


def test_m5_topology_covers_route_privacy_wait_approval_and_verify() -> None:
    assert M5_GRAPH_NODES == (
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
    assert ("review_m5_privacy:open_findings", "wait_m5_privacy_resolution") in M5_GRAPH_EDGES
    assert ("wait_m5_approval:explicit_action", "validate_m5_approval") in M5_GRAPH_EDGES
    assert ("validate_m5_approval:denied_or_stale", "terminalize_m5_run") in M5_GRAPH_EDGES


def test_m5_checkpoint_accepts_only_bounded_ids_and_hashes() -> None:
    validated = validate_m5_graph_state(valid_state())
    assert set(validated.as_graph_state()) == M5_GRAPH_STATE_ALLOWED_KEYS

    for forbidden in (
        "canonical_asset",
        "source_text",
        "raw_prompt",
        "raw_response",
        "route_draft_body",
        "approved",
        "filesystem_path",
    ):
        payload = valid_state()
        payload[forbidden] = "private or browser-controlled content"
        with pytest.raises(ValueError, match="forbidden fields"):
            validate_m5_graph_state(payload)


def test_approval_checkpoint_requires_both_policy_bindings() -> None:
    payload = valid_state()
    payload["approval_id"] = str(uuid4())
    with pytest.raises(ValidationError, match="draft and privacy binding"):
        M5GraphStateV1.model_validate(payload)


def test_checkpoint_manifest_tracks_the_isolated_workflow_identity() -> None:
    manifest = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    assert manifest["scope"] == "FULL_E6_M5_NO_REDUCTION"
    assert manifest["e5_handoff"]["valid_outcomes"] == [
        "NO_MATCH",
        "DECLINED",
        "CONFIRMED_RELATION",
        "STALE",
    ]
    assert manifest["e5_handoff"]["snapshot_embedding_forbidden"] is True
    assert manifest["approval"]["preview_implies_approval"] is False
    assert manifest["workflow"]["topology_hash"] == M5_TOPOLOGY_HASH
    assert manifest["evidence"]["device_claim"] == "NOT_MADE_BY_ISOLATED_CHECKPOINT"
