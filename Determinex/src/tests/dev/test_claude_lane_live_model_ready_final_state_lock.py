"""Tests for CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_LOCK_001."""

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

final_mod = importlib.import_module("dev.claude_lane_live_model_ready_final_state")
rec_mod = importlib.import_module("dev.claude_lane_live_model_ready_final_state_record")

assemble = final_mod.assemble_live_model_ready_final_state
upstream_locks = final_mod.upstream_locks
TOKENS = rec_mod.CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_TOKENS

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "claude_lane_live_model_ready_final_state"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"

STATUS_TOKENS = frozenset(TOKENS)


def test_status_tokens_match_expected_set():
    expected = {
        "CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_WRITTEN",
        "EXECUTION_SURFACE_CLEAN",
        "MODEL_ROUTING_READY",
        "LIVE_MODEL_ADMISSION_READY_OPT_IN_LOCAL_ONLY",
        "NETWORK_MODELS_BLOCKED_BY_DEFAULT",
        "DIAGNOSE_ONLY_TRACE_READY",
        "PATCH_PLAN_QUARANTINE_READY",
        "TEMP_PATCH_VERIFIER_GATE_READY",
        "SOURCE_MUTATION_BLOCKED_PENDING_HUMAN_APPROVAL",
        "IDE_LIVE_STATE_READY",
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
    assert state.execution_surface == "CLEAN"
    assert state.model_routing == "READY"
    assert state.live_model_admission == "READY_OPT_IN_LOCAL_ONLY"
    assert state.network_models == "BLOCKED_BY_DEFAULT"
    assert state.diagnose_only_trace == "READY"
    assert state.patch_plan_quarantine == "READY"
    assert state.temp_patch_verifier_gate == "READY"
    assert state.source_mutation == "BLOCKED_PENDING_HUMAN_APPROVAL"
    assert state.ide_live_state == "READY"
    assert state.training_eligibility == "BLOCKED_BY_DEFAULT"
    assert state.release_readiness == "NOT_RELEASED"
    assert state.next_unblocker == "REAL_LOCAL_MODEL_CONFIG_AND_HUMAN_APPROVAL_UI"


def test_state_json_round_trip():
    state = assemble()
    parsed = json.loads(state.to_json())
    assert parsed["live_model_admission"] == "READY_OPT_IN_LOCAL_ONLY"
    assert parsed["training_eligibility"] == "BLOCKED_BY_DEFAULT"


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in (
        "claude_lane_live_model_ready_final_state.py",
        "claude_lane_live_model_ready_final_state_record.py",
    ):
        src = (_REPO_ROOT / "scripts" / "dev" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src


def test_assembly_does_not_run_subprocess(monkeypatch):
    import subprocess as _sp

    called = {"count": 0}
    original_run = _sp.run

    def _spy(*args, **kwargs):  # pragma: no cover
        called["count"] += 1
        return original_run(*args, **kwargs)

    monkeypatch.setattr(_sp, "run", _spy)
    assemble()
    assert called["count"] == 0


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_LOCK_001" in ids
