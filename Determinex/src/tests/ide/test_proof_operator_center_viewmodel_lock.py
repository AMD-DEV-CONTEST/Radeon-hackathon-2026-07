"""Tests for DETERMINEX_PROOF_OPERATOR_CENTER_VIEWMODEL_LOCK_001."""

from __future__ import annotations

import dataclasses
import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

pc = importlib.import_module("ide.proof_operator_center_viewmodel")
pc_rec = importlib.import_module("ide.proof_operator_center_viewmodel_record")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_PROOF_OPERATOR_CENTER_VIEWMODEL_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_proof_operator_center_viewmodel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _action(label="Request approval", routes_to="external_approval_workflow"):
    return pc_rec.OperatorAction(
        label=label,
        kind="request",
        visible=True,
        routes_to=routes_to,
    )


def _vm(**overrides):
    base = dict(
        workspace_identity_hash="a" * 64,
        evidence_count=42,
        source_mutation_authorized_now=False,
        training_eligible_now=False,
        verifier_status_text="post-apply verifier: passed",
        rollback_status_text="snapshot available",
        operator_actions=(_action(),),
        blocked_actions_visible=True,
        blocked_actions_text="apply disabled until approval present",
        programbench_provenance_read_only=True,
        programbench_status_text="ProgramBench: read-only mirror from Codex lane",
        training_status_text="training_eligible: false (remains false)",
        claim_safety_status_text="all claims classified per ledger",
    )
    base.update(overrides)
    return pc_rec.ProofOperatorCenterViewModel(**base)


# ---------------------------------------------------------------------------
# Tokens / sections
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(pc_rec.PROOF_OPERATOR_CENTER_VIEWMODEL_STATUS_TOKENS) == {
        "PROOF_OPERATOR_CENTER_VIEWMODEL_WRITTEN",
        "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_ACTION_HIDDEN",
        "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION",
        "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_TRAINING_CONFUSION",
    }


def test_sections_exact():
    assert pc.canonical_sections() == (
        "evidence_ledger",
        "current_workspace_status",
        "source_mutation_gates",
        "verifier_status",
        "rollback_status",
        "operator_actions",
        "programbench_provenance_status_read_only",
        "training_eligibility_status",
        "claim_safety_status",
        "blocked_actions",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_canonical_view_model_is_written():
    rec = pc.build(_vm())
    assert rec.is_written, rec.notes
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


# ---------------------------------------------------------------------------
# Training confusion
# ---------------------------------------------------------------------------
def test_training_eligible_now_true_blocks():
    rec = pc.build(_vm(training_eligible_now=True))
    assert rec.decision == "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_TRAINING_CONFUSION"


def test_training_status_text_missing_false_blocks():
    rec = pc.build(_vm(training_status_text="training: see settings"))
    assert rec.decision == "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_TRAINING_CONFUSION"


# ---------------------------------------------------------------------------
# Action hidden
# ---------------------------------------------------------------------------
def test_blocked_actions_hidden_blocks():
    rec = pc.build(_vm(blocked_actions_visible=False))
    assert rec.decision == "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_ACTION_HIDDEN"


def test_blocked_actions_text_empty_blocks():
    rec = pc.build(_vm(blocked_actions_text=""))
    assert rec.decision == "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_ACTION_HIDDEN"


def test_none_view_model_blocks():
    rec = pc.build(None)
    assert rec.is_blocked


# ---------------------------------------------------------------------------
# Authority confusion — operator actions
# ---------------------------------------------------------------------------
def test_grant_kind_action_blocks():
    bad = dataclasses.replace(_action(), kind="grant")
    rec = pc.build(_vm(operator_actions=(bad,)))
    assert rec.decision == "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION"


def test_visible_action_without_routes_to_blocks():
    bad = dataclasses.replace(_action(), routes_to="")
    rec = pc.build(_vm(operator_actions=(bad,)))
    assert rec.decision == "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION"


def test_hidden_action_without_routes_to_passes():
    """An invisible action is fine without a route."""
    hidden = dataclasses.replace(_action(), visible=False, routes_to="")
    rec = pc.build(_vm(operator_actions=(hidden,)))
    assert rec.is_written


# ---------------------------------------------------------------------------
# Authority confusion — source mutation
# ---------------------------------------------------------------------------
def test_source_mutation_authorized_now_true_blocks():
    rec = pc.build(_vm(source_mutation_authorized_now=True))
    assert rec.decision == "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION"


# ---------------------------------------------------------------------------
# Authority confusion — ProgramBench mutability
# ---------------------------------------------------------------------------
def test_programbench_provenance_writable_blocks():
    rec = pc.build(_vm(programbench_provenance_read_only=False))
    assert rec.decision == "PROOF_OPERATOR_CENTER_VIEWMODEL_BLOCKED_AUTHORITY_CONFUSION"


# ---------------------------------------------------------------------------
# Invariants / serialization
# ---------------------------------------------------------------------------
def test_passed_record_never_authorizes_anything():
    rec = pc.build(_vm())
    assert rec.is_written
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_record_serializes():
    rec = pc.build(_vm())
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "PROOF_OPERATOR_CENTER_VIEWMODEL_WRITTEN"
    assert len(blob["sections_present"]) == 10


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_PROOF_OPERATOR_CENTER_VIEWMODEL_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_PROOF_OPERATOR_CENTER_VIEWMODEL_LOCK_001" in ids
