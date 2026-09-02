"""Tests for DETERMINEX_REACT_REPO_CLINIC_PANEL_LOCK_001."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PANEL_PATH = (
    _REPO_ROOT / "frontend" / "src" / "components" / "ide-product-shell" / "RepoClinicPanel.tsx"
)
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_REACT_REPO_CLINIC_PANEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_react_repo_clinic_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _src() -> str:
    return PANEL_PATH.read_text(encoding="utf-8")


def test_panel_file_exists():
    assert PANEL_PATH.is_file()


def test_status_tokens_declared():
    src = _src()
    for t in (
        "REACT_REPO_CLINIC_PANEL_PASSED",
        "REACT_REPO_CLINIC_PANEL_BLOCKED_FALSE_FIXED_LABEL",
        "REACT_REPO_CLINIC_PANEL_BLOCKED_SOURCE_MUTATION_CONFUSION",
        "REACT_REPO_CLINIC_PANEL_BLOCKED_VERIFIER_MISSING_HIDDEN",
    ):
        assert t in src


def test_required_sections_present():
    src = _src()
    for tid in (
        "repo-clinic-repo-analysis-status",
        "repo-clinic-toolchain-status",
        "repo-clinic-verifier-status",
        "repo-clinic-diagnosis-status",
        "repo-clinic-quarantined-patch-status",
        "repo-clinic-temp-verifier-status",
        "repo-clinic-approval-requirement",
        "repo-clinic-source-mutation-status",
        "repo-clinic-post-apply-verifier-status",
        "repo-clinic-rollback-status",
        "repo-clinic-evidence-status",
        "repo-clinic-training-eligibility-status",
    ):
        assert f'data-testid="{tid}"' in src, tid


def test_verifier_missing_state_visible():
    src = _src()
    assert 'data-testid="repo-clinic-verifier-missing-badge"' in src
    assert "VERIFIER_MISSING" in src
    assert "TOOLCHAIN_MISSING" in src


def test_fixed_label_gated_on_post_apply_verifier():
    src = _src()
    assert "sourceMutationApplied && postApplyVerifierPassed" in src
    assert "FIXED_LABEL_DISABLED_NO_POST_APPLY_EVIDENCE" in src
    assert "REPAIR_VERIFIED" in src
    assert 'data-testid="repo-clinic-fixed-meaning"' in src
    assert "post-apply verifier pass" in src


def test_diagnosis_does_not_authorize():
    src = _src()
    assert 'data-testid="repo-clinic-diagnosis-not-authorization"' in src
    assert "Diagnosis does NOT authorize source mutation." in src


def test_admission_does_not_authorize_source_mutation():
    src = _src()
    assert 'data-testid="repo-clinic-admission-not-source-authorization"' in src
    assert "Local model admission does NOT authorize source mutation." in src


def test_approval_distinct_from_source_mutation_applied():
    src = _src()
    assert 'data-testid="repo-clinic-source-mutation-distinct"' in src
    assert "distinct from approval status" in src


def test_training_status_false_everywhere():
    src = _src()
    assert "training_eligible: false" in src
    assert "remains false" in src


def test_no_false_fixed_text_without_evidence():
    """If sourceMutationApplied && postApplyVerifierPassed are both
    false, the panel must NOT render unqualified success."""
    src = _src().lower()
    for f in ("repair complete!", "everything is fixed", "all clear"):
        assert f not in src, f


def test_no_mutating_command_invoked():
    src = _src()
    # Allow multi-line formatted call.
    assert "invokeUnifiedProductCommand(" in src
    assert '"get_repo_clinic_workflow_state"' in src
    for forbidden in ("apply_source", "approve_packet", "write_training", "release_workflow"):
        assert forbidden not in src


def test_ready_does_not_mean_authorized_present():
    src = _src()
    assert "READY_DOES_NOT_MEAN_AUTHORIZED" in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_REACT_REPO_CLINIC_PANEL_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    assert sorted(EVIDENCE_DIR.glob("run_*.json"))


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_REACT_REPO_CLINIC_PANEL_LOCK_001" in ids
