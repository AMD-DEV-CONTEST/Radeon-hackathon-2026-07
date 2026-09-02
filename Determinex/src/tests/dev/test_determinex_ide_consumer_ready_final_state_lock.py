"""Tests for DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_LOCK_001."""

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

final_mod = importlib.import_module("dev.determinex_ide_consumer_ready_final_state")
rec_mod = importlib.import_module("dev.determinex_ide_consumer_ready_final_state_record")

assemble = final_mod.assemble_consumer_ready_final_state
upstream_locks = final_mod.upstream_locks
TOKENS = rec_mod.DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_TOKENS

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_ide_consumer_ready_final_state"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"

STATUS_TOKENS = frozenset(TOKENS)


def test_status_tokens_match_expected_set():
    expected = {
        "DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_WRITTEN",
        "LOCAL_MODEL_CONFIG_READY_OPT_IN",
        "LOCAL_PROVIDER_SMOKE_READY",
        "LIVE_DIAGNOSE_COMMAND_READY_OPT_IN",
        "PATCH_PLAN_COMMAND_READY_QUARANTINE",
        "TEMP_PATCH_VERIFY_COMMAND_READY_TEMP_ONLY",
        "HUMAN_APPROVAL_UI_MODEL_READY",
        "IDE_BACKEND_COMMAND_SURFACE_READY",
        "SOURCE_APPLY_DRY_RUN_READY_NO_MUTATION",
        "IDE_CONSUMER_FLOW_TRACE_READY",
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
    state = assemble()
    assert state.local_model_config == "READY_OPT_IN"
    assert state.local_provider_smoke == "READY"
    assert state.live_diagnose_command == "READY_OPT_IN"
    assert state.patch_plan_command == "READY_QUARANTINE"
    assert state.temp_patch_verify_command == "READY_TEMP_ONLY"
    assert state.human_approval_ui_model == "READY"
    assert state.ide_backend_command_surface == "READY"
    assert state.source_apply_dry_run == "READY_NO_MUTATION"
    assert state.ide_consumer_flow_trace == "READY"
    assert state.source_mutation == "BLOCKED_PENDING_REAL_HUMAN_APPROVAL"
    assert state.training_eligibility == "BLOCKED_BY_DEFAULT"
    assert state.release_readiness == "NOT_RELEASED"
    assert state.next_unblocker == "FRONTEND_UI_AND_REAL_USER_APPROVAL_FLOW"


def test_state_json_round_trip():
    state = assemble()
    parsed = json.loads(state.to_json())
    assert parsed["training_eligibility"] == "BLOCKED_BY_DEFAULT"
    assert parsed["source_mutation"] == "BLOCKED_PENDING_REAL_HUMAN_APPROVAL"


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in (
        "determinex_ide_consumer_ready_final_state.py",
        "determinex_ide_consumer_ready_final_state_record.py",
    ):
        src = (_REPO_ROOT / "scripts" / "dev" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_LOCK_001" in ids
