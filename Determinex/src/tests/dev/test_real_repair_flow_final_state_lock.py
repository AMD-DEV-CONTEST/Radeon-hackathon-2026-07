"""Tests for REAL_REPAIR_FLOW_FINAL_STATE_LOCK_001."""

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

final_mod = importlib.import_module("dev.real_repair_flow_final_state")
rec_mod = importlib.import_module("dev.real_repair_flow_final_state_record")

assemble = final_mod.assemble_real_repair_flow_final_state
upstream_locks = final_mod.upstream_locks
TOKENS = rec_mod.REAL_REPAIR_FLOW_FINAL_STATE_TOKENS

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_REPAIR_FLOW_FINAL_STATE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_repair_flow_final_state"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"

STATUS_TOKENS = frozenset(TOKENS)


def test_status_tokens_exact():
    expected = {
        "REAL_REPAIR_FLOW_FINAL_STATE_WRITTEN",
        "REAL_LOCAL_MODEL_PROVIDER_READY_OR_BLOCKED_WITH_REASON",
        "REAL_MODEL_ADMISSION_READY_OPT_IN",
        "LIVE_DIAGNOSE_READY_ADVISORY_ONLY",
        "PATCH_PLAN_QUARANTINE_READY",
        "TEMP_PATCH_VERIFIER_READY_HUMAN_APPROVAL_REQUIRED",
        "HUMAN_APPROVAL_READY_REAL_SIGNED_ONLY",
        "ROLLBACK_SNAPSHOT_READY",
        "SOURCE_APPLY_AFTER_APPROVAL_READY_GATED",
        "POST_APPLY_VERIFIER_READY",
        "ROLLBACK_STATUS_READY_ON_FAIL",
        "SOURCE_MUTATION_GATED_BY_REAL_APPROVAL",
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
    assert s.real_local_model_provider == "READY_OR_BLOCKED_WITH_REASON"
    assert s.real_model_admission == "READY_OPT_IN"
    assert s.live_diagnose == "READY_ADVISORY_ONLY"
    assert s.patch_plan_quarantine == "READY"
    assert s.temp_patch_verifier == "READY_HUMAN_APPROVAL_REQUIRED"
    assert s.human_approval == "READY_REAL_SIGNED_ONLY"
    assert s.rollback_snapshot == "READY"
    assert s.source_apply_after_approval == "READY_GATED"
    assert s.post_apply_verifier == "READY"
    assert s.rollback_status == "READY_ON_FAIL"
    assert s.source_mutation == "GATED_BY_REAL_APPROVAL"
    assert s.training_eligibility == "BLOCKED_BY_DEFAULT"
    assert s.release_readiness == "NOT_RELEASED"
    assert s.next_unblocker == "REAL_BUILD_ADAPTER_BACKED_VERIFIER_AND_REAL_LOCAL_MODEL_PULLED"


def test_state_json_round_trip():
    s = assemble()
    parsed = json.loads(s.to_json())
    assert parsed["source_mutation"] == "GATED_BY_REAL_APPROVAL"
    assert parsed["training_eligibility"] == "BLOCKED_BY_DEFAULT"
    assert parsed["release_readiness"] == "NOT_RELEASED"


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in (
        "real_repair_flow_final_state.py",
        "real_repair_flow_final_state_record.py",
    ):
        src = (_REPO_ROOT / "scripts" / "dev" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src
        assert "import socket" not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_REPAIR_FLOW_FINAL_STATE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    sd = blob.get("scope_discipline", {})
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("network_provider_admitted") is False
    assert sd.get("docker_used") is False
    assert sd.get("release_workflow_added") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_REPAIR_FLOW_FINAL_STATE_LOCK_001" in ids
