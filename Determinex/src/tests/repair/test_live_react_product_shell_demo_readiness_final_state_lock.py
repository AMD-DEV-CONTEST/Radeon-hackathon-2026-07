"""Tests for DETERMINEX_LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_LOCK_001."""

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

final = importlib.import_module("repair.live_react_product_shell_demo_readiness_final_state")

LOCK_PATH = (
    _REPO_ROOT
    / "locks"
    / "sentinel"
    / ("DETERMINEX_LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_LOCK_001.json")
)
EVIDENCE_DIR = (
    _REPO_ROOT
    / "assurance"
    / "evidence"
    / ("determinex_live_react_product_shell_demo_readiness_final_state")
)
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Live evaluation
# ---------------------------------------------------------------------------
def test_live_evaluation_passes():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.is_passed, rec.notes


def test_all_two_dimensions_closed():
    # Was four; verified_demo_binding and release_blocker_panel were dropped
    # 2026-07-20 -- their panels+locks+tests were deliberately archived
    # (commit 30b3ff570) as a Claude<->Codex tandem-pipeline trail, not real
    # features. Requiring their (now-deleted) lock files here was a stale
    # check pointing at intentionally-removed work, not a real gap.
    rec = final.evaluate(_REPO_ROOT)
    assert rec.browser_snapshot_closed
    assert rec.happy_blocked_path_closed


def test_aggregate_invariants():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False
    assert rec.release_ready is False
    assert rec.unsupported_claims_blocked is True


def test_next_recommended_is_repo_clinic_fixture_repair():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.next_recommended_rung == (
        "DETERMINEX_REPO_CLINIC_FIXTURE_REPAIR_SPLASH_DEMO_LOCK_001"
    )


# ---------------------------------------------------------------------------
# Synthetic
# ---------------------------------------------------------------------------
def _mirror(tmp_path: Path) -> Path:
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
    fake = _mirror(tmp_path)
    rec = final.evaluate(fake)
    assert rec.is_passed, rec.notes


def test_missing_browser_snapshot_rung_blocks(tmp_path):
    fake = _mirror(tmp_path)
    (
        fake
        / "locks"
        / "sentinel"
        / "DETERMINEX_REACT_PRODUCT_SHELL_BROWSER_SNAPSHOT_LOCK_001.json"
    ).unlink()
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.browser_snapshot_closed is False


def test_lock_with_opened_source_mutation_blocks(tmp_path):
    # Was DETERMINEX_REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_LOCK_001
    # (deleted 2026-07-20, see module docstring) -- retargeted to a
    # surviving rung, same invariant (opening source_mutation_authorized on
    # any rung blocks the finale).
    fake = _mirror(tmp_path)
    target = (
        fake
        / "locks"
        / "sentinel"
        / "DETERMINEX_REACT_DEMO_NAVIGATION_HAPPY_BLOCKED_PATH_LOCK_001.json"
    )
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["source_mutation_authorized"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.happy_blocked_path_closed is False


def test_lock_with_release_ready_true_blocks(tmp_path):
    # Was DETERMINEX_REACT_RELEASE_READINESS_BLOCKER_PANEL_LOCK_001
    # (deleted 2026-07-20, see module docstring) -- retargeted to a
    # surviving rung, same invariant (an unsupported claim key set True on
    # any rung blocks the finale).
    fake = _mirror(tmp_path)
    target = (
        fake
        / "locks"
        / "sentinel"
        / "DETERMINEX_REACT_PRODUCT_SHELL_BROWSER_SNAPSHOT_LOCK_001.json"
    )
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["release_ready_set_true"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.unsupported_claims_blocked is False


def test_lock_with_broad_public_claims_granted_blocks(tmp_path):
    # Was DETERMINEX_REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_LOCK_001
    # (deleted 2026-07-20, see module docstring) -- retargeted to a
    # surviving rung.
    fake = _mirror(tmp_path)
    target = (
        fake
        / "locks"
        / "sentinel"
        / "DETERMINEX_REACT_PRODUCT_SHELL_BROWSER_SNAPSHOT_LOCK_001.json"
    )
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["broad_public_claims_granted"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == (
        "DETERMINEX_LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_LOCK_001"
    )
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    assert sorted(EVIDENCE_DIR.glob("run_*.json"))


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_LOCK_001" in ids
