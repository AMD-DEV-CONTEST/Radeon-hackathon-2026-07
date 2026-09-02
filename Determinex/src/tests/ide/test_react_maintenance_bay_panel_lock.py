"""Tests for DETERMINEX_REACT_MAINTENANCE_BAY_PANEL_LOCK_001."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PANEL_PATH = (
    _REPO_ROOT / "frontend" / "src" / "components" / "ide-product-shell" / "MaintenanceBayPanel.tsx"
)
LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_REACT_MAINTENANCE_BAY_PANEL_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_react_maintenance_bay_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _src() -> str:
    return PANEL_PATH.read_text(encoding="utf-8")


def test_panel_file_exists():
    assert PANEL_PATH.is_file()


def test_status_tokens_declared():
    src = _src()
    for t in (
        "REACT_MAINTENANCE_BAY_PANEL_PASSED",
        "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_FALSE_UPDATED_LABEL",
        "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_MISSING_COMPATIBILITY_VERIFIER",
        "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_RISK_HIDDEN",
    ):
        assert t in src


def test_required_sections_present():
    src = _src()
    for tid in (
        "maintenance-bay-request-type",
        "maintenance-bay-risk-classification",
        "maintenance-bay-impact-plan",
        "maintenance-bay-quarantined-changes",
        "maintenance-bay-compatibility-verifier-required",
        "maintenance-bay-approval-requirement",
        "maintenance-bay-post-apply-verifier",
        "maintenance-bay-rollback-evidence",
        "maintenance-bay-training-eligibility",
    ):
        assert f'data-testid="{tid}"' in src, tid


def test_updated_label_gated_on_full_chain():
    src = _src()
    # All four flags must participate in the gate (whitespace-insensitive).
    compact = " ".join(src.split())
    assert (
        "compatibilityVerifierPresent && compatibilityVerifierPassed && approvalPresent && postApplyVerifierPassed"
        in compact
    )
    assert "UPDATED_LABEL_DISABLED_NO_VERIFIER" in src
    assert "UPDATE_APPLIED_AFTER_APPROVAL" in src
    assert 'data-testid="maintenance-bay-updated-meaning"' in src


def test_risk_visible_required_for_dependency_security():
    src = _src()
    assert 'data-testid="maintenance-bay-risk-visible"' in src
    assert "must be set for dependency/security" in src or "UNDISCLOSED" in src
    assert "riskRequiredForType" in src


def test_advisory_caveat_visible():
    src = _src()
    assert 'data-testid="maintenance-bay-advisory-caveat"' in src
    assert "Advisory / scanner status caveated" in src
    assert "ADVISORY_UNCAVEATED" in src


def test_proposed_is_not_applied_caption_present():
    src = _src()
    assert 'data-testid="maintenance-bay-proposed-is-not-applied"' in src
    assert "Proposed is NOT applied" in src
    assert "quarantined is NOT verified" in src


def test_training_status_false_everywhere():
    src = _src()
    assert "training_eligible: false" in src
    assert "remains false" in src


def test_no_mutating_command_invoked():
    src = _src()
    assert "invokeUnifiedProductCommand(" in src
    assert '"get_maintenance_bay_workflow_state"' in src
    for forbidden in ("apply_source", "approve_packet", "write_training", "release_workflow"):
        assert forbidden not in src


def test_no_false_updated_text_without_evidence():
    src = _src().lower()
    for f in ("dependency updated!", "all dependencies up to date", "production-ready"):
        assert f not in src, f


def test_ready_does_not_mean_authorized_present():
    src = _src()
    assert "READY_DOES_NOT_MEAN_AUTHORIZED" in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_REACT_MAINTENANCE_BAY_PANEL_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    assert sorted(EVIDENCE_DIR.glob("run_*.json"))


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_REACT_MAINTENANCE_BAY_PANEL_LOCK_001" in ids
