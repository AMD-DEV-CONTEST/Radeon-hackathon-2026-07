"""Tests for DETERMINEX_IDEA_LAB_WORKFLOW_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

il = importlib.import_module("ide.idea_lab_workflow")
il_rec = importlib.import_module("ide.idea_lab_workflow_record")

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_IDEA_LAB_WORKFLOW_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_idea_lab_workflow"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _default(**overrides):
    base = dict(
        build_it_enabled=False,
        working_label_enabled=False,
        unsupported_features_visible=True,
        external_caveats_visible=True,
        support_check_passed=False,
        build_verifier_passed=False,
        tests_passed=False,
        smoke_passed=False,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tokens / states / flow
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(il_rec.IDEA_LAB_WORKFLOW_STATUS_TOKENS) == {
        "IDEA_LAB_WORKFLOW_WRITTEN",
        "IDEA_LAB_WORKFLOW_BLOCKED_UNSUPPORTED_CLAIM",
        "IDEA_LAB_WORKFLOW_BLOCKED_FALSE_SUCCESS",
        "IDEA_LAB_WORKFLOW_BLOCKED_MISSING_SUPPORT_CHECK",
    }


def test_states_exact():
    assert il.canonical_states() == (
        "IDEA_CAPTURED",
        "SPEC_WRITTEN",
        "SUPPORT_CHECK_REQUIRED",
        "UNSUPPORTED_REQUEST",
        "BLUEPRINT_READY",
        "SCAFFOLD_READY",
        "GENERATED_UNVERIFIED",
        "TESTS_PASSED",
        "SMOKE_PASSED",
        "VERIFIED_WORKING_LOCAL_APP",
        "HONEST_FAILURE",
    )


def test_flow_steps_exact():
    assert il.canonical_flow_steps() == (
        "idea_intake",
        "structured_spec",
        "beginner_summary",
        "support_matrix_check",
        "blueprint",
        "scaffold_request",
        "acceptance_tests",
        "implementation_plan",
        "build_test_verifier",
        "smoke_plan",
        "bounded_repair_plan",
        "final_report",
        "evidence",
        "training_remains_blocked",
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------
def test_idle_workflow_with_caveats_visible_is_written():
    """Build It off, Working off, caveats visible — clean state."""
    rec = il.evaluate(**_default())
    assert rec.is_written, rec.notes


def test_build_it_enabled_after_support_check_pass_is_written():
    rec = il.evaluate(
        **_default(
            build_it_enabled=True,
            support_check_passed=True,
        )
    )
    assert rec.is_written, rec.notes


def test_working_label_after_full_evidence_is_written():
    rec = il.evaluate(
        **_default(
            build_it_enabled=True,
            support_check_passed=True,
            working_label_enabled=True,
            build_verifier_passed=True,
            tests_passed=True,
            smoke_passed=True,
        )
    )
    assert rec.is_written, rec.notes


# ---------------------------------------------------------------------------
# Unsupported / caveats refusals
# ---------------------------------------------------------------------------
def test_hidden_unsupported_features_blocks():
    rec = il.evaluate(**_default(unsupported_features_visible=False))
    assert rec.decision == "IDEA_LAB_WORKFLOW_BLOCKED_UNSUPPORTED_CLAIM"


def test_hidden_external_caveats_blocks():
    rec = il.evaluate(**_default(external_caveats_visible=False))
    assert rec.decision == "IDEA_LAB_WORKFLOW_BLOCKED_UNSUPPORTED_CLAIM"


# ---------------------------------------------------------------------------
# Support check refusal
# ---------------------------------------------------------------------------
def test_build_it_enabled_without_support_check_blocks():
    rec = il.evaluate(**_default(build_it_enabled=True))
    assert rec.decision == "IDEA_LAB_WORKFLOW_BLOCKED_MISSING_SUPPORT_CHECK"


# ---------------------------------------------------------------------------
# False-success refusals
# ---------------------------------------------------------------------------
def test_working_label_without_build_verifier_blocks():
    rec = il.evaluate(
        **_default(
            build_it_enabled=True,
            support_check_passed=True,
            working_label_enabled=True,
            tests_passed=True,
            smoke_passed=True,
            # build_verifier_passed=False
        )
    )
    assert rec.decision == "IDEA_LAB_WORKFLOW_BLOCKED_FALSE_SUCCESS"


def test_working_label_without_tests_passed_blocks():
    rec = il.evaluate(
        **_default(
            build_it_enabled=True,
            support_check_passed=True,
            working_label_enabled=True,
            build_verifier_passed=True,
            smoke_passed=True,
            # tests_passed=False
        )
    )
    assert rec.decision == "IDEA_LAB_WORKFLOW_BLOCKED_FALSE_SUCCESS"


def test_working_label_without_smoke_blocks():
    rec = il.evaluate(
        **_default(
            build_it_enabled=True,
            support_check_passed=True,
            working_label_enabled=True,
            build_verifier_passed=True,
            tests_passed=True,
            # smoke_passed=False
        )
    )
    assert rec.decision == "IDEA_LAB_WORKFLOW_BLOCKED_FALSE_SUCCESS"


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------
def test_record_never_authorizes_source_mutation():
    rec = il.evaluate(
        **_default(
            build_it_enabled=True,
            support_check_passed=True,
            working_label_enabled=True,
            build_verifier_passed=True,
            tests_passed=True,
            smoke_passed=True,
        )
    )
    assert rec.is_written
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_record_serializes():
    rec = il.evaluate(**_default())
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "IDEA_LAB_WORKFLOW_WRITTEN"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_IDEA_LAB_WORKFLOW_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_IDEA_LAB_WORKFLOW_LOCK_001" in ids
