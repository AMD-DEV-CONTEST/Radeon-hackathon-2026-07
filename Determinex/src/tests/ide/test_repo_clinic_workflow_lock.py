"""Tests for DETERMINEX_REPO_CLINIC_WORKFLOW_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

rc = importlib.import_module("ide.repo_clinic_workflow")
rc_rec = importlib.import_module("ide.repo_clinic_workflow_record")

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_REPO_CLINIC_WORKFLOW_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_repo_clinic_workflow"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _state(**overrides):
    base = dict(
        fixed_label_enabled=False,
        verifier_command_present=True,
        temp_verifier_passed=False,
        approval_present=False,
        source_mutation_attempted=False,
        source_mutation_authorized_by_gate=False,
        post_apply_verifier_passed=False,
        diagnosis_treated_as_authorization=False,
        local_model_admission_treated_as_source_authorization=False,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Status tokens / inventory
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(rc_rec.REPO_CLINIC_WORKFLOW_STATUS_TOKENS) == {
        "REPO_CLINIC_WORKFLOW_WRITTEN",
        "REPO_CLINIC_WORKFLOW_BLOCKED_VERIFIER_MISSING",
        "REPO_CLINIC_WORKFLOW_BLOCKED_FALSE_FIXED_LABEL",
        "REPO_CLINIC_WORKFLOW_BLOCKED_SOURCE_MUTATION_CONFUSION",
    }


def test_states_inventory():
    expected = {
        "REPO_OPENED",
        "REPO_ANALYZED",
        "TOOLCHAIN_MISSING",
        "VERIFIER_MISSING",
        "ISSUE_DIAGNOSED_UNVERIFIED",
        "PATCH_PROPOSED_QUARANTINED",
        "TEMP_VERIFIER_PASSED",
        "APPROVAL_REQUIRED",
        "SOURCE_MUTATION_AUTHORIZED",
        "SOURCE_MUTATION_APPLIED",
        "POST_APPLY_VERIFIER_PASSED",
        "REPAIR_VERIFIED",
        "REPAIR_FAILED_HONESTLY",
    }
    assert set(rc.canonical_states()) == expected


def test_flow_steps_inventory():
    steps = rc.canonical_flow_steps()
    assert "verifier_discovery" in steps
    assert "quarantine" in steps
    assert "temp_apply" in steps
    assert "source_mutation_after_approval_only" in steps
    assert "post_apply_verifier" in steps
    assert "rollback_if_failed" in steps
    assert "training_remains_blocked" in steps


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------
def test_idle_state_is_written():
    rec = rc.evaluate(**_state())
    assert rec.is_written


def test_full_repair_path_is_written():
    rec = rc.evaluate(
        **_state(
            temp_verifier_passed=True,
            approval_present=True,
            source_mutation_attempted=True,
            source_mutation_authorized_by_gate=True,
            post_apply_verifier_passed=True,
            fixed_label_enabled=True,
        )
    )
    assert rec.is_written


# ---------------------------------------------------------------------------
# Verifier missing
# ---------------------------------------------------------------------------
def test_no_verifier_with_source_mutation_attempt_blocks():
    rec = rc.evaluate(
        **_state(
            verifier_command_present=False,
            source_mutation_attempted=True,
        )
    )
    assert rec.decision == "REPO_CLINIC_WORKFLOW_BLOCKED_VERIFIER_MISSING"


def test_no_verifier_with_fixed_label_blocks():
    rec = rc.evaluate(
        **_state(
            verifier_command_present=False,
            fixed_label_enabled=True,
        )
    )
    assert rec.decision == "REPO_CLINIC_WORKFLOW_BLOCKED_VERIFIER_MISSING"


def test_no_verifier_idle_state_passes():
    """If nothing is being attempted, missing verifier is fine."""
    rec = rc.evaluate(**_state(verifier_command_present=False))
    assert rec.is_written


# ---------------------------------------------------------------------------
# Source mutation confusion
# ---------------------------------------------------------------------------
def test_diagnosis_as_authorization_blocks():
    rec = rc.evaluate(**_state(diagnosis_treated_as_authorization=True))
    assert rec.decision == "REPO_CLINIC_WORKFLOW_BLOCKED_SOURCE_MUTATION_CONFUSION"


def test_local_model_admission_as_authorization_blocks():
    rec = rc.evaluate(
        **_state(
            local_model_admission_treated_as_source_authorization=True,
        )
    )
    assert rec.decision == "REPO_CLINIC_WORKFLOW_BLOCKED_SOURCE_MUTATION_CONFUSION"


def test_gate_authorized_without_temp_verifier_blocks():
    rec = rc.evaluate(
        **_state(
            source_mutation_authorized_by_gate=True,
            approval_present=True,
            # temp_verifier_passed=False
        )
    )
    assert rec.decision == "REPO_CLINIC_WORKFLOW_BLOCKED_SOURCE_MUTATION_CONFUSION"


def test_gate_authorized_without_approval_blocks():
    rec = rc.evaluate(
        **_state(
            source_mutation_authorized_by_gate=True,
            temp_verifier_passed=True,
            # approval_present=False
        )
    )
    assert rec.decision == "REPO_CLINIC_WORKFLOW_BLOCKED_SOURCE_MUTATION_CONFUSION"


# ---------------------------------------------------------------------------
# False fixed label
# ---------------------------------------------------------------------------
def test_fixed_label_without_post_apply_verifier_blocks():
    rec = rc.evaluate(
        **_state(
            verifier_command_present=True,
            temp_verifier_passed=True,
            approval_present=True,
            source_mutation_authorized_by_gate=True,
            source_mutation_attempted=True,
            fixed_label_enabled=True,
            # post_apply_verifier_passed=False
        )
    )
    assert rec.decision == "REPO_CLINIC_WORKFLOW_BLOCKED_FALSE_FIXED_LABEL"


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------
def test_record_never_authorizes_source_or_training():
    rec = rc.evaluate(
        **_state(
            temp_verifier_passed=True,
            approval_present=True,
            source_mutation_authorized_by_gate=True,
            post_apply_verifier_passed=True,
            fixed_label_enabled=True,
        )
    )
    assert rec.is_written
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_record_serializes():
    rec = rc.evaluate(**_state())
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "REPO_CLINIC_WORKFLOW_WRITTEN"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_REPO_CLINIC_WORKFLOW_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_REPO_CLINIC_WORKFLOW_LOCK_001" in ids
