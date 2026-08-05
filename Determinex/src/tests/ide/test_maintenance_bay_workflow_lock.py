"""Tests for DETERMINEX_MAINTENANCE_BAY_WORKFLOW_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mb = importlib.import_module("ide.maintenance_bay_workflow")
mb_rec = importlib.import_module("ide.maintenance_bay_workflow_record")

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_MAINTENANCE_BAY_WORKFLOW_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_maintenance_bay_workflow"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _state(**overrides):
    base = dict(
        maintenance_type="dependency_update",
        risk_visible=True,
        compatibility_verifier_present=True,
        compatibility_verifier_passed=False,
        advisory_status_caveated=True,
        approval_present=False,
        update_proposed_quarantined=True,
        update_applied_label_enabled=False,
        updated_label_enabled=False,
        post_apply_verifier_passed=False,
        rollback_plan_present=True,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tokens / inventory
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(mb_rec.MAINTENANCE_BAY_WORKFLOW_STATUS_TOKENS) == {
        "MAINTENANCE_BAY_WORKFLOW_WRITTEN",
        "MAINTENANCE_BAY_WORKFLOW_BLOCKED_FALSE_UPDATED_LABEL",
        "MAINTENANCE_BAY_WORKFLOW_BLOCKED_MISSING_COMPATIBILITY_VERIFIER",
        "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION",
    }


def test_maintenance_types_exact():
    assert mb.canonical_maintenance_types() == (
        "dependency_update",
        "security_fix",
        "docs_update",
        "test_hardening",
        "refactor",
        "migration",
        "formatting_lint_cleanup",
        "performance_cleanup",
    )


def test_states_exact():
    assert mb.canonical_states() == (
        "MAINTENANCE_REQUESTED",
        "MAINTENANCE_PLAN_WRITTEN",
        "UPDATE_PROPOSED_QUARANTINED",
        "COMPATIBILITY_VERIFIER_REQUIRED",
        "UPDATE_VERIFIED",
        "UPDATE_BLOCKED_UNVERIFIED",
        "UPDATE_APPLIED_AFTER_APPROVAL",
        "UPDATE_FAILED_HONESTLY",
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------
def test_idle_request_is_written():
    rec = mb.evaluate(**_state())
    assert rec.is_written


def test_docs_update_with_basic_requirements_is_written():
    rec = mb.evaluate(**_state(maintenance_type="docs_update"))
    assert rec.is_written


def test_full_dep_update_applied_after_approval_is_written():
    rec = mb.evaluate(
        **_state(
            compatibility_verifier_passed=True,
            approval_present=True,
            update_applied_label_enabled=True,
            updated_label_enabled=True,
            post_apply_verifier_passed=True,
        )
    )
    assert rec.is_written


# ---------------------------------------------------------------------------
# Unknown type
# ---------------------------------------------------------------------------
def test_unknown_type_blocks():
    rec = mb.evaluate(**_state(maintenance_type="reformat_universe"))
    assert rec.decision == "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION"


# ---------------------------------------------------------------------------
# Dependency / security require risk + advisory caveat
# ---------------------------------------------------------------------------
def test_dep_update_without_risk_visible_blocks():
    rec = mb.evaluate(**_state(risk_visible=False))
    assert rec.decision == "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION"


def test_security_fix_without_advisory_caveat_blocks():
    rec = mb.evaluate(
        **_state(
            maintenance_type="security_fix",
            advisory_status_caveated=False,
        )
    )
    assert rec.decision == "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION"


def test_docs_update_without_risk_passes():
    """docs_update doesn't require risk_visible — it's low-risk by nature."""
    rec = mb.evaluate(
        **_state(
            maintenance_type="docs_update",
            risk_visible=False,
        )
    )
    assert rec.is_written


# ---------------------------------------------------------------------------
# Compatibility verifier missing
# ---------------------------------------------------------------------------
def test_applied_label_without_compatibility_verifier_blocks():
    rec = mb.evaluate(
        **_state(
            update_applied_label_enabled=True,
            compatibility_verifier_present=False,
        )
    )
    assert rec.decision == "MAINTENANCE_BAY_WORKFLOW_BLOCKED_MISSING_COMPATIBILITY_VERIFIER"


# ---------------------------------------------------------------------------
# False updated label
# ---------------------------------------------------------------------------
def test_updated_label_without_post_apply_verifier_blocks():
    rec = mb.evaluate(
        **_state(
            compatibility_verifier_passed=True,
            approval_present=True,
            update_applied_label_enabled=True,
            updated_label_enabled=True,
            # post_apply_verifier_passed=False
        )
    )
    assert rec.decision == "MAINTENANCE_BAY_WORKFLOW_BLOCKED_FALSE_UPDATED_LABEL"


# ---------------------------------------------------------------------------
# Proposed -> applied confusion
# ---------------------------------------------------------------------------
def test_applied_label_without_approval_blocks():
    rec = mb.evaluate(
        **_state(
            compatibility_verifier_passed=True,
            update_applied_label_enabled=True,
            # approval_present=False
        )
    )
    assert rec.decision == "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION"


def test_applied_label_without_compatibility_verifier_pass_blocks():
    rec = mb.evaluate(
        **_state(
            approval_present=True,
            update_applied_label_enabled=True,
            # compatibility_verifier_passed=False
        )
    )
    assert rec.decision == "MAINTENANCE_BAY_WORKFLOW_BLOCKED_AUTHORITY_CONFUSION"


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------
def test_record_never_authorizes_mutation():
    rec = mb.evaluate(
        **_state(
            compatibility_verifier_passed=True,
            approval_present=True,
            update_applied_label_enabled=True,
            updated_label_enabled=True,
            post_apply_verifier_passed=True,
        )
    )
    assert rec.is_written
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_record_serializes():
    rec = mb.evaluate(**_state())
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "MAINTENANCE_BAY_WORKFLOW_WRITTEN"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_MAINTENANCE_BAY_WORKFLOW_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_MAINTENANCE_BAY_WORKFLOW_LOCK_001" in ids
