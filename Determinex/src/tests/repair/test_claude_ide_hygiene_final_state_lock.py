"""Tests for CLAUDE_IDE_HYGIENE_FINAL_STATE_LOCK_001 (rung 9 finale)."""

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

final = importlib.import_module("repair.claude_ide_hygiene_final_state")

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / ("CLAUDE_IDE_HYGIENE_FINAL_STATE_LOCK_001.json")
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / ("claude_ide_hygiene_final_state")
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Live evaluation
# ---------------------------------------------------------------------------
def test_live_evaluation_passes():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.is_passed, f"finale evaluator did not pass; notes={rec.notes!r}"


def test_live_evaluation_all_dimensions_closed():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.ready_authorized_language_closed
    assert rec.operator_identity_bounding_closed
    assert rec.approval_replay_staleness_closed
    assert rec.pre_apply_confirmation_closed
    assert rec.config_root_allowlist_closed
    assert rec.frontend_authority_visuals_closed
    assert rec.public_claims_ledger_closed
    assert rec.demo_script_closed


def test_aggregate_invariants():
    rec = final.evaluate(_REPO_ROOT)
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False
    assert rec.release_ready is False
    assert rec.demo_ready is True


def test_forge_and_mobile_status():
    rec = final.evaluate(_REPO_ROOT)
    assert "planned" in rec.forge_status
    assert "planned" in rec.mobile_console_status


# ---------------------------------------------------------------------------
# Synthetic
# ---------------------------------------------------------------------------
def _mirror_repo_skeleton(tmp_path: Path) -> Path:
    fake = tmp_path / "fake-repo"
    (fake / "locks" / "sentinel").mkdir(parents=True)
    (fake / "assurance" / "evidence").mkdir(parents=True)
    for lid, _ in final._RUNG_LOCKS.values():
        src = _REPO_ROOT / "locks" / "sentinel" / f"{lid}.json"
        dst = fake / "locks" / "sentinel" / f"{lid}.json"
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


def test_synthetic_full_skeleton_passes(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    rec = final.evaluate(fake)
    assert rec.is_passed, rec.notes


def test_missing_rung_blocks(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    (fake / "locks" / "sentinel" / "CLAUDE_PUBLIC_CLAIMS_LEDGER_LOCK_001.json").unlink()
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.public_claims_ledger_closed is False
    assert rec.demo_ready is True  # demo rung still present


def test_lock_with_open_source_mutation_blocks(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    target = fake / "locks" / "sentinel" / "CLAUDE_CONFIG_ROOT_ALLOWLIST_LOCK_001.json"
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["source_mutation_authorized"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.config_root_allowlist_closed is False


def test_lock_with_opened_training_blocks(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    target = fake / "locks" / "sentinel" / "CLAUDE_PRE_APPLY_CONFIRMATION_PANEL_LOCK_001.json"
    blob = json.loads(target.read_text(encoding="utf-8"))
    blob["scope_discipline"]["training_eligible"] = True
    target.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.pre_apply_confirmation_closed is False


def test_missing_demo_rung_sets_demo_ready_false(tmp_path):
    fake = _mirror_repo_skeleton(tmp_path)
    (
        fake / "locks" / "sentinel" / "CLAUDE_PROOF_BEFORE_MUTATION_DEMO_SCRIPT_LOCK_001.json"
    ).unlink()
    rec = final.evaluate(fake)
    assert rec.is_blocked
    assert rec.demo_script_closed is False
    assert rec.demo_ready is False


# ---------------------------------------------------------------------------
# Deferred findings
# ---------------------------------------------------------------------------
def test_deferred_findings_announced():
    rec = final.evaluate(_REPO_ROOT)
    assert "CLAUDE-AUTH-010" in rec.deferred_findings
    assert "CLAUDE-AUTH-017" in rec.deferred_findings


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_IDE_HYGIENE_FINAL_STATE_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_IDE_HYGIENE_FINAL_STATE_LOCK_001" in ids
