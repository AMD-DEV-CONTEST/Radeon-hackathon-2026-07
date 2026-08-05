"""Tests for CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_LOCK_001 (rung 9).

The finale asserts that all eight authority-leak dimensions are
closed AND the campaign opens neither source_mutation_authorized
nor training_eligible.

These tests:
  - Verify the live evaluator against the on-disk locks (umbrella
    claim must pass right now).
  - Verify the evaluator correctly BLOCKS when one of the eight
    rung manifests is missing or its scope_discipline is wrong
    (using a synthetic repo root in a tmpdir).
  - Verify lock/evidence/index artifacts are present.
"""

from __future__ import annotations

import importlib
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

final = importlib.import_module("repair.claude_authority_leak_remediation_final_state")
final_rec = importlib.import_module("repair.claude_authority_leak_remediation_final_state_record")

LOCK_PATH = (
    _REPO_ROOT
    / "locks"
    / "sentinel"
    / ("CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_LOCK_001.json")
)
EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / ("claude_authority_leak_remediation_final_state")
)
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Live evaluation
# ---------------------------------------------------------------------------
def test_live_evaluation_passes():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.is_passed, (
        f"finale evaluator did not pass; decision={rec.decision!r}; notes={rec.notes!r}"
    )


def test_live_evaluation_all_dimensions_closed():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.diff_body_binding_closed
    assert rec.fixture_refusal_closed
    assert rec.post_apply_verifier_default_pass_closed
    assert rec.model_admission_bypass_closed
    assert rec.tauri_command_alignment_closed
    assert rec.diagnose_prompt_opacity_closed
    assert rec.approval_signature_binding_closed
    assert rec.rollback_symlink_semantics_closed


def test_live_evaluation_invariants_remain_negative():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_live_evaluation_safe_for_cross_lane_boundary():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.safe_for_cross_lane_boundary is True


def test_findings_remediated_and_deferred_sets_are_disjoint():
    rec = final.evaluate(_REPO_ROOT)
    assert set(rec.findings_remediated).isdisjoint(set(rec.findings_deferred))
    assert "CLAUDE-AUTH-001" in rec.findings_remediated
    assert "CLAUDE-AUTH-005" in rec.findings_deferred


# ---------------------------------------------------------------------------
# Synthetic repo — missing rung blocks
# ---------------------------------------------------------------------------
def _mirror_repo_skeleton(tmp_path: Path) -> Path:
    """Copy enough of the repo to drive the evaluator: locks/ +
    the evidence directories referenced by the lock manifests."""
    fake = tmp_path / "fake-repo"
    (fake / "locks" / "sentinel").mkdir(parents=True)
    (fake / "assurance" / "evidence").mkdir(parents=True)
    for lid in final._RUNG_LOCKS.values():
        lock_id = lid[0]
        src = _REPO_ROOT / "locks" / "sentinel" / f"{lock_id}.json"
        dst = fake / "locks" / "sentinel" / f"{lock_id}.json"
        shutil.copy2(src, dst)
        # Also copy the evidence artifact path declared in the manifest.
        blob = json.loads(src.read_text(encoding="utf-8"))
        ev = (blob.get("evidence") or {}).get("run_artifact")
        if ev:
            ev_src = _REPO_ROOT / ev
            ev_dst = fake / ev
            ev_dst.parent.mkdir(parents=True, exist_ok=True)
            if ev_src.is_file():
                shutil.copy2(ev_src, ev_dst)
    return fake


def test_synthetic_repo_passes_when_complete(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    rec = final.evaluate(fake)
    assert rec.is_passed, rec.notes


def test_missing_rung_lock_manifest_blocks(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    # Remove the rung-1 lock.
    (fake / "locks" / "sentinel" / "REAL_APPROVAL_DIFF_BODY_CONTENT_BINDING_LOCK_001.json").unlink()
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.decision == (
        "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED"
    )
    assert rec.diff_body_binding_closed is False
    assert rec.safe_for_cross_lane_boundary is False


def test_lock_with_open_source_mutation_blocks(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    target = fake / "locks" / "sentinel" / "ROLLBACK_SYMLINK_SEMANTICS_LOCK_001.json"
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["source_mutation_authorized"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.rollback_symlink_semantics_closed is False
    assert rec.safe_for_cross_lane_boundary is False


def test_lock_with_open_training_eligibility_blocks(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    target = fake / "locks" / "sentinel" / "APPROVAL_SIGNATURE_CRYPTOGRAPHIC_BINDING_LOCK_001.json"
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["training_eligibility_opened"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.approval_signature_binding_closed is False
    assert rec.safe_for_cross_lane_boundary is False


# ---------------------------------------------------------------------------
# Manifest / evidence / index artifacts
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_LOCK_001"
    cts = blob.get("campaign_terminal_state") or {}
    assert cts.get("safe_for_cross_lane_boundary") is True
    assert cts.get("rungs_completed") == 9
    assert cts.get("dimensions_closed") == 8
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_LOCK_001" in ids
