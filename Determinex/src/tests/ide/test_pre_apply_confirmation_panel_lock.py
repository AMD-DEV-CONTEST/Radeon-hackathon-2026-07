"""Tests for CLAUDE_PRE_APPLY_CONFIRMATION_PANEL_LOCK_001."""

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

pp = importlib.import_module("ide.pre_apply_confirmation_panel")
pp_rec = importlib.import_module("ide.pre_apply_confirmation_panel_record")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / ("CLAUDE_PRE_APPLY_CONFIRMATION_PANEL_LOCK_001.json")
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / ("claude_pre_apply_confirmation_panel")
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


_CONSEQUENCE = (
    "Source mutation will write files; post-apply verifier will run and may trigger rollback."
)
_TRAINING = "Training eligibility remains False unless separately gated."


def _vm(**overrides):
    base = dict(
        ui_state="PRE_APPLY_UI_APPROVED",
        files_affected=("src/a.py",),
        canonical_patch_body_hash="b" * 64,
        diff_hash="d" * 64,
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        rollback_snapshot_ref="snap-1",
        source_mutation_consequence_text=_CONSEQUENCE,
        training_eligibility_text=_TRAINING,
        source_mutation_authorized=False,
    )
    base.update(overrides)
    return pp.build_view_model(**base)


# ---------------------------------------------------------------------------
# Status tokens / ui states
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(pp_rec.PRE_APPLY_CONFIRMATION_PANEL_STATUS_TOKENS) == {
        "PRE_APPLY_CONFIRMATION_PANEL_PASSED",
        "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_HASH",
        "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_VERIFIER",
        "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY",
        "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_SNAPSHOT",
        "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_TRAINING_OPENED",
    }


def test_ui_states_exact():
    assert pp.PRE_APPLY_UI_STATES == (
        "PRE_APPLY_UI_PREVIEW",
        "PRE_APPLY_UI_DRY_RUN",
        "PRE_APPLY_UI_APPROVED",
        "PRE_APPLY_UI_SOURCE_MUTATION_AUTHORIZED",
        "PRE_APPLY_UI_SOURCE_MUTATION_APPLIED",
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------
def test_preview_state_passes_without_snapshot():
    vm = _vm(ui_state="PRE_APPLY_UI_PREVIEW", rollback_snapshot_ref="")
    rec = pp.check(vm)
    assert rec.is_passed, rec.notes
    assert rec.source_mutation_authorized is False


def test_dry_run_state_passes_without_snapshot():
    vm = _vm(ui_state="PRE_APPLY_UI_DRY_RUN", rollback_snapshot_ref="")
    rec = pp.check(vm)
    assert rec.is_passed, rec.notes


def test_approved_state_requires_snapshot():
    rec = pp.check(_vm())
    assert rec.is_passed


def test_authorized_state_passes_with_consequence_text():
    vm = _vm(
        ui_state="PRE_APPLY_UI_SOURCE_MUTATION_AUTHORIZED",
        source_mutation_authorized=True,
    )
    rec = pp.check(vm)
    assert rec.is_passed
    assert rec.source_mutation_authorized is True
    assert rec.training_eligible is False


def test_applied_state_carries_authorized_flag():
    vm = _vm(
        ui_state="PRE_APPLY_UI_SOURCE_MUTATION_APPLIED",
        source_mutation_authorized=True,
    )
    rec = pp.check(vm)
    assert rec.is_passed


# ---------------------------------------------------------------------------
# Required-field refusals
# ---------------------------------------------------------------------------
def test_missing_canonical_body_hash_blocks():
    rec = pp.check(_vm(canonical_patch_body_hash=""))
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_HASH"


def test_missing_diff_hash_blocks():
    rec = pp.check(_vm(diff_hash=""))
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_HASH"


def test_missing_verifier_status_blocks():
    rec = pp.check(_vm(verifier_status=""))
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_VERIFIER"


def test_missing_snapshot_in_approved_state_blocks():
    rec = pp.check(_vm(ui_state="PRE_APPLY_UI_APPROVED", rollback_snapshot_ref=""))
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_SNAPSHOT"


def test_missing_snapshot_in_authorized_state_blocks():
    rec = pp.check(
        _vm(
            ui_state="PRE_APPLY_UI_SOURCE_MUTATION_AUTHORIZED",
            source_mutation_authorized=True,
            rollback_snapshot_ref="",
        )
    )
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_SNAPSHOT"


# ---------------------------------------------------------------------------
# Authority ambiguity refusals
# ---------------------------------------------------------------------------
def test_unknown_ui_state_blocks():
    vm = _vm(ui_state="UNKNOWN")
    rec = pp.check(vm)
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY"


def test_authorized_flag_in_preview_state_blocks():
    vm = _vm(
        ui_state="PRE_APPLY_UI_PREVIEW",
        rollback_snapshot_ref="",
        source_mutation_authorized=True,
    )
    rec = pp.check(vm)
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY"


def test_authorized_flag_in_approved_state_blocks():
    """APPROVED means operator approved; mutation has not happened.
    Setting source_mutation_authorized=True in this state is
    ambiguous — that flag belongs only to AUTHORIZED/APPLIED."""
    vm = _vm(source_mutation_authorized=True)  # default ui_state=APPROVED
    rec = pp.check(vm)
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY"


def test_applied_without_authorized_flag_blocks():
    vm = _vm(
        ui_state="PRE_APPLY_UI_SOURCE_MUTATION_APPLIED",
        source_mutation_authorized=False,
    )
    rec = pp.check(vm)
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY"


def test_authorized_state_with_weak_consequence_text_blocks():
    vm = _vm(
        ui_state="PRE_APPLY_UI_SOURCE_MUTATION_AUTHORIZED",
        source_mutation_authorized=True,
        source_mutation_consequence_text="OK",
    )
    rec = pp.check(vm)
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY"


def test_authorized_state_with_weak_training_text_blocks():
    vm = _vm(
        ui_state="PRE_APPLY_UI_SOURCE_MUTATION_AUTHORIZED",
        source_mutation_authorized=True,
        training_eligibility_text="(none)",
    )
    rec = pp.check(vm)
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY"


# ---------------------------------------------------------------------------
# Training never opened
# ---------------------------------------------------------------------------
def test_panel_with_training_eligible_true_blocks():
    vm = dataclasses.replace(_vm(), training_eligible=True)
    rec = pp.check(vm)
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_TRAINING_OPENED"


def test_build_view_model_never_sets_training_eligible_true():
    vm = pp.build_view_model(
        ui_state="PRE_APPLY_UI_PREVIEW",
        files_affected=("a.py",),
        canonical_patch_body_hash="b" * 64,
        diff_hash="d" * 64,
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        rollback_snapshot_ref="snap-1",
        source_mutation_consequence_text=_CONSEQUENCE,
        training_eligibility_text=_TRAINING,
        source_mutation_authorized=True,
    )
    assert vm.training_eligible is False


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def test_none_panel_blocks():
    rec = pp.check(None)
    assert rec.decision == "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY"


def test_view_model_files_affected_is_tuple():
    vm = _vm(files_affected=["a.py", "b.py"])
    assert isinstance(vm.files_affected, tuple)


def test_passed_panel_view_model_serializable():
    vm = _vm()
    rec = pp.check(vm)
    assert rec.is_passed
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "PRE_APPLY_CONFIRMATION_PANEL_PASSED"
    assert blob["panel"]["canonical_patch_body_hash"] == "b" * 64


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_PRE_APPLY_CONFIRMATION_PANEL_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_PRE_APPLY_CONFIRMATION_PANEL_LOCK_001" in ids
