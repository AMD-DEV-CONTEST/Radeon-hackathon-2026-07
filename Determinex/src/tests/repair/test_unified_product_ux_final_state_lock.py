"""Tests for DETERMINEX_UNIFIED_PRODUCT_UX_FINAL_STATE_LOCK_001 (rung 9 finale)."""

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

final = importlib.import_module("repair.unified_product_ux_final_state")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_UNIFIED_PRODUCT_UX_FINAL_STATE_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_unified_product_ux_final_state"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Live evaluation
# ---------------------------------------------------------------------------
def test_live_evaluation_passes():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.is_passed, rec.notes


def test_live_evaluation_all_eight_dimensions_closed():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.navigation_model_closed
    assert rec.idea_lab_workflow_closed
    assert rec.repo_clinic_workflow_closed
    assert rec.maintenance_bay_workflow_closed
    assert rec.learning_studio_workflow_closed
    assert rec.proof_operator_center_viewmodel_closed
    assert rec.user_levels_teaching_windows_closed
    assert rec.splash_demo_spec_closed


def test_aggregate_invariants():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False
    assert rec.release_ready is False
    assert rec.unsupported_claims_blocked is True


def test_next_recommended_rung_set():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.next_recommended_rung.strip()


# ---------------------------------------------------------------------------
# Synthetic
# ---------------------------------------------------------------------------
def _mirror_repo_skeleton(tmp_path: Path) -> Path:
    fake = tmp_path / "fake-repo"
    (fake / "locks" / "sentinel").mkdir(parents=True)
    (fake / "assurance" / "evidence").mkdir(parents=True)
    for lock_id in final._RUNG_LOCKS.values():
        src = _REPO_ROOT / "locks" / "sentinel" / f"{lock_id}.json"
        dst = fake / "locks" / "sentinel" / f"{lock_id}.json"
        shutil.copy2(src, dst)
        blob = json.loads(src.read_text(encoding="utf-8"))
        ev = (blob.get("evidence") or {}).get("run_artifact")
        if ev:
            src_ev = _REPO_ROOT / ev
            dst_ev = fake / ev
            dst_ev.parent.mkdir(parents=True, exist_ok=True)
            if src_ev.is_file():
                shutil.copy2(src_ev, dst_ev)
    return fake


def test_synthetic_skeleton_passes(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    rec = final.evaluate(fake)
    assert rec.is_passed, rec.notes


def test_missing_navigation_rung_blocks(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    (
        fake / "locks" / "sentinel" / "DETERMINEX_UNIFIED_PRODUCT_NAVIGATION_MODEL_LOCK_001.json"
    ).unlink()
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.navigation_model_closed is False


def test_lock_with_opened_source_mutation_blocks(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    target = fake / "locks" / "sentinel" / "DETERMINEX_REPO_CLINIC_WORKFLOW_LOCK_001.json"
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["source_mutation_authorized"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.repo_clinic_workflow_closed is False


def test_lock_with_opened_training_blocks(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    target = fake / "locks" / "sentinel" / "DETERMINEX_LEARNING_STUDIO_WORKFLOW_LOCK_001.json"
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["training_eligible"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.learning_studio_workflow_closed is False


def test_lock_with_unsupported_claim_blocks(tmp_path):
    """If any rung's scope_discipline opens an unsupported-claim
    key (all_apps_claim, all_languages_claim, etc.), the finale
    blocks."""
    fake = _mirror_repo_skeleton(tmp_path)
    target = fake / "locks" / "sentinel" / "DETERMINEX_IDEA_LAB_WORKFLOW_LOCK_001.json"
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["all_apps_claim"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.unsupported_claims_blocked is False


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_UNIFIED_PRODUCT_UX_FINAL_STATE_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_UNIFIED_PRODUCT_UX_FINAL_STATE_LOCK_001" in ids
