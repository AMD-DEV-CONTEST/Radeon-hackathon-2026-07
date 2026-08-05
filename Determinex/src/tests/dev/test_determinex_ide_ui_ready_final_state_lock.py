"""Tests for DETERMINEX_IDE_UI_READY_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

final_mod = importlib.import_module("dev.determinex_ide_ui_ready_final_state")
rec_mod = importlib.import_module("dev.determinex_ide_ui_ready_final_state_record")

assemble = final_mod.assemble_ui_ready_final_state
upstream_locks = final_mod.upstream_locks
TOKENS = rec_mod.DETERMINEX_IDE_UI_READY_FINAL_STATE_TOKENS

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_IDE_UI_READY_FINAL_STATE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_ide_ui_ready_final_state"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"

STATUS_TOKENS = frozenset(TOKENS)


def test_status_tokens_match_expected_set():
    expected = {
        "DETERMINEX_IDE_UI_READY_FINAL_STATE_WRITTEN",
        "WORKSPACE_OPEN_FLOW_READY",
        "MODEL_ROUTE_PANEL_READY",
        "DIAGNOSE_FLOW_READY",
        "PATCH_PLAN_FLOW_READY_QUARANTINE",
        "TEMP_VERIFY_FLOW_READY_TEMP_ONLY",
        "HUMAN_APPROVAL_SIGNING_FLOW_READY",
        "SOURCE_APPLY_GATE_FLOW_READY_DRY_RUN_ONLY",
        "TAURI_BACKEND_BRIDGE_READY",
        "FRONTEND_STATE_CONTRACT_READY",
        "APPROVAL_UX_COPY_READY",
        "END_TO_END_UI_FLOW_TRACE_READY",
        "SOURCE_MUTATION_BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
        "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
        "RELEASE_READINESS_NOT_RELEASED",
        "NEXT_UNBLOCKER_DECLARED",
    }
    assert set(STATUS_TOKENS) == expected


@pytest.mark.parametrize("lock_name", upstream_locks())
def test_every_upstream_lock_is_present(lock_name):
    assert (LOCKS_DIR / f"{lock_name}.json").is_file(), f"Missing: {lock_name}"


def test_assembly_reports_no_missing_locks():
    state = assemble()
    assert state.upstream_locks_missing == ()


def test_final_dimensions():
    s = assemble()
    assert s.workspace_open_flow == "READY"
    assert s.model_route_panel == "READY"
    assert s.diagnose_flow == "READY"
    assert s.patch_plan_flow == "READY_QUARANTINE"
    assert s.temp_verify_flow == "READY_TEMP_ONLY"
    assert s.human_approval_signing_flow == "READY"
    assert s.source_apply_gate_flow == "READY_DRY_RUN_ONLY"
    assert s.tauri_backend_bridge == "READY"
    assert s.frontend_state_contract == "READY"
    assert s.approval_ux_copy == "READY"
    assert s.end_to_end_ui_flow_trace == "READY"
    assert s.source_mutation == "BLOCKED_PENDING_REAL_HUMAN_APPROVAL"
    assert s.training_eligibility == "BLOCKED_BY_DEFAULT"
    assert s.release_readiness == "NOT_RELEASED"
    assert s.next_unblocker == "REAL_FRONTEND_IMPLEMENTATION_AND_REAL_LOCAL_MODEL_CONFIG"


def test_state_json_round_trip():
    s = assemble()
    parsed = json.loads(s.to_json())
    assert parsed["source_mutation"] == "BLOCKED_PENDING_REAL_HUMAN_APPROVAL"
    assert parsed["training_eligibility"] == "BLOCKED_BY_DEFAULT"


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in (
        "determinex_ide_ui_ready_final_state.py",
        "determinex_ide_ui_ready_final_state_record.py",
    ):
        src = (_REPO_ROOT / "scripts" / "dev" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_IDE_UI_READY_FINAL_STATE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_IDE_UI_READY_FINAL_STATE_LOCK_001" in ids
