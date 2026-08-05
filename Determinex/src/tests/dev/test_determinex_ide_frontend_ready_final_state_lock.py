"""Tests for DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_LOCK_001."""

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

final_mod = importlib.import_module("dev.determinex_ide_frontend_ready_final_state")
rec_mod = importlib.import_module("dev.determinex_ide_frontend_ready_final_state_record")

assemble = final_mod.assemble_frontend_ready_final_state
upstream_locks = final_mod.upstream_locks
TOKENS = rec_mod.DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_TOKENS

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_ide_frontend_ready_final_state"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"

STATUS_TOKENS = frozenset(TOKENS)


def test_status_tokens_match_expected_set():
    expected = {
        "DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_WRITTEN",
        "TAURI_RUST_COMMAND_BRIDGE_READY",
        "FRONTEND_REPAIR_PANEL_SHELL_READY",
        "FRONTEND_WORKSPACE_STATUS_PANEL_READY",
        "FRONTEND_MODEL_ROUTE_PANEL_READY",
        "FRONTEND_DIAGNOSE_AND_PATCH_PLAN_FLOW_READY",
        "FRONTEND_TEMP_VERIFY_PANEL_READY",
        "FRONTEND_HUMAN_APPROVAL_PANEL_READY",
        "FRONTEND_SOURCE_APPLY_DRY_RUN_PANEL_READY",
        "FRONTEND_EVIDENCE_VIEWER_READY",
        "LOCAL_MODEL_SETTINGS_PANEL_READY",
        "FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_READY",
        "SOURCE_MUTATION_BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
        "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
        "LIVE_MODEL_CALL_BLOCKED_BY_DEFAULT",
        "NETWORK_PROVIDER_BLOCKED_BY_DEFAULT",
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
    assert s.tauri_rust_command_bridge == "READY_AS_STANDALONE_MODULE"
    assert s.frontend_repair_panel_shell == "READY"
    assert s.frontend_workspace_status_panel == "READY"
    assert s.frontend_model_route_panel == "READY"
    assert s.frontend_diagnose_and_patch_plan_flow == "READY_OPT_IN_GATED"
    assert s.frontend_temp_verify_panel == "READY_TEMP_ONLY"
    assert s.frontend_human_approval_panel == "READY_FIXTURE_APPROVAL_ONLY"
    assert s.frontend_source_apply_dry_run_panel == "READY_NO_REAL_APPLY"
    assert s.frontend_evidence_viewer == "READY_READ_ONLY"
    assert s.local_model_settings_panel == "READY_NO_LIVE_CALL_ON_SAVE"
    assert s.frontend_end_to_end_repair_flow_smoke == "READY"
    assert s.source_mutation == "BLOCKED_PENDING_REAL_HUMAN_APPROVAL"
    assert s.training_eligibility == "BLOCKED_BY_DEFAULT"
    assert s.live_model_call == "BLOCKED_BY_DEFAULT"
    assert s.network_provider == "BLOCKED_BY_DEFAULT"
    assert s.release_readiness == "NOT_RELEASED"
    assert s.next_unblocker == "REAL_TAURI_LIB_RS_WIRING_AND_LIVE_LOCAL_MODEL_PROVIDER"


def test_state_json_round_trip():
    s = assemble()
    parsed = json.loads(s.to_json())
    assert parsed["source_mutation"] == "BLOCKED_PENDING_REAL_HUMAN_APPROVAL"
    assert parsed["training_eligibility"] == "BLOCKED_BY_DEFAULT"
    assert parsed["live_model_call"] == "BLOCKED_BY_DEFAULT"
    assert parsed["network_provider"] == "BLOCKED_BY_DEFAULT"


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in (
        "determinex_ide_frontend_ready_final_state.py",
        "determinex_ide_frontend_ready_final_state_record.py",
    ):
        src = (_REPO_ROOT / "scripts" / "dev" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src
        assert "import socket" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("live_model_called") is False
    assert sd.get("network_provider_admitted") is False
    assert sd.get("release_workflow_added") is False
    assert sd.get("tauri_lib_rs_modified") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_LOCK_001" in ids
