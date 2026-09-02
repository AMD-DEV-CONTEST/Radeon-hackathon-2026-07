"""Tests for FRONTEND_REAL_FLOW_E2E_LOCK_001."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ide.frontend_real_flow_e2e import (
    FRONTEND_REAL_FLOW_E2E_TOKENS,
    FrontendRealFlowE2ETrace,
    run_real_flow_e2e,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_REAL_FLOW_E2E_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_real_flow_e2e"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "FRONTEND_REAL_FLOW_E2E_PASSED",
        "FRONTEND_REAL_FLOW_SOURCE_UNCHANGED",
        "FRONTEND_REAL_FLOW_APPROVAL_REQUIRED",
        "FRONTEND_REAL_FLOW_TRAINING_ELIGIBLE_FALSE",
        "FRONTEND_REAL_FLOW_NETWORK_PROVIDER_BLOCKED",
        "FRONTEND_REAL_FLOW_DOCKER_NOT_USED",
        "FRONTEND_REAL_FLOW_FE_BE_STATES_AGREE",
    }
)

EXPECTED_STAGE_NAMES = (
    "open workspace",
    "inspect status",
    "route model",
    "diagnose dry-run",
    "patch plan quarantine",
    "temp verify",
    "approval packet",
    "source apply dry-run",
    "evidence viewer",
)


def test_status_tokens_exact():
    assert set(FRONTEND_REAL_FLOW_E2E_TOKENS) == EXPECTED


def test_all_nine_stages_present_in_order():
    t = run_real_flow_e2e()
    names = tuple(s.name for s in t.stages)
    assert names == EXPECTED_STAGE_NAMES


def test_no_stage_authorizes_source_or_training():
    t = run_real_flow_e2e()
    for s in t.stages:
        assert s.source_mutation_authorized is False, s.name
        assert s.training_eligible is False, s.name


def test_every_stage_attaches_evidence_ref():
    t = run_real_flow_e2e()
    for s in t.stages:
        assert s.evidence_ref, f"{s.name} missing evidence_ref"
        # Ref must point at an existing on-disk artifact.
        assert (_REPO_ROOT / s.evidence_ref).is_file(), s.evidence_ref


def test_trace_invariants():
    t = run_real_flow_e2e()
    assert isinstance(t, FrontendRealFlowE2ETrace)
    assert t.source_unchanged is True
    assert t.approval_required is True
    assert t.training_eligible is False
    assert t.network_called is False
    assert t.docker_used is False
    assert t.frontend_backend_states_agree is True


def test_statuses_seen_only_in_safe_set():
    t = run_real_flow_e2e()
    safe_tauri = {
        "TAURI_COMMAND_OK",
        "TAURI_COMMAND_TEMP_ONLY",
        "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
        "TAURI_COMMAND_BLOCKED_NOT_OPTED_IN",
        "TAURI_COMMAND_BLOCKED_NO_MODEL",
    }
    safe_e2e = set(FRONTEND_REAL_FLOW_E2E_TOKENS)
    allowed = safe_tauri | safe_e2e
    seen = set(t.statuses_seen)
    leftover = seen - allowed
    assert not leftover, f"unexpected statuses seen: {leftover}"


def test_module_does_not_spawn_subprocess_or_open_network():
    import scripts.ide.frontend_real_flow_e2e as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "requests",
        "httpx",
        "urllib.request",
        "socket.connect",
        "subprocess.Popen",
        "subprocess.run",
        "docker.from_env",
        "docker.client",
    ):
        assert forbidden not in src, forbidden


def test_trace_serializes_with_safe_flags():
    t = run_real_flow_e2e()
    d = t.to_dict()
    json.dumps(d)
    assert d["source_unchanged"] is True
    assert d["training_eligible"] is False
    assert d["network_called"] is False
    assert d["docker_used"] is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_REAL_FLOW_E2E_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("network_called") is False
    assert sd.get("docker_used") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_REAL_FLOW_E2E_LOCK_001" in ids
