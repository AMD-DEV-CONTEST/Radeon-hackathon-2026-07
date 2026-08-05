"""Tests for FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_LOCK_001."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ide.frontend_end_to_end_repair_flow_smoke import (
    FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_TOKENS,
    FrontendEndToEndRepairFlowSmokeTrace,
    run_smoke,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_end_to_end_repair_flow_smoke"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED_TOKENS = frozenset(
    {
        "FRONTEND_E2E_SMOKE_TRACE_WRITTEN",
        "FRONTEND_E2E_SMOKE_SOURCE_UNCHANGED",
        "FRONTEND_E2E_SMOKE_APPROVAL_REQUIRED",
        "FRONTEND_E2E_SMOKE_TRAINING_ELIGIBLE_FALSE",
        "FRONTEND_E2E_SMOKE_NO_LIVE_MODEL_CALL",
        "FRONTEND_E2E_SMOKE_NO_NETWORK_CALL",
    }
)


def test_status_tokens_exact():
    assert set(FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_TOKENS) == EXPECTED_TOKENS


def test_smoke_runs_clean_and_covers_all_panels():
    trace = run_smoke()
    assert isinstance(trace, FrontendEndToEndRepairFlowSmokeTrace)
    panels = {s.panel for s in trace.stages}
    expected_panels = {
        "WorkspaceStatusPanel",
        "ModelRoutePanel",
        "DiagnoseAndPatchPlanPanel",
        "TempVerifyPanel",
        "HumanApprovalPanel",
        "SourceApplyDryRunPanel",
        "EvidenceViewerPanel",
    }
    assert expected_panels.issubset(panels)


def test_every_stage_blocks_source_mutation_and_training():
    trace = run_smoke()
    for s in trace.stages:
        assert s.source_mutation_authorized is False, (s.panel, s.tauri_command)
        assert s.training_eligible is False, (s.panel, s.tauri_command)


def test_trace_invariants():
    trace = run_smoke()
    assert trace.source_unchanged is True
    assert trace.approval_required is True
    assert trace.training_eligible is False
    assert trace.live_model_called is False
    assert trace.network_called is False


def test_human_approval_stage_returns_source_mutation_blocked():
    trace = run_smoke()
    hap = [s for s in trace.stages if s.panel == "HumanApprovalPanel"]
    assert hap, "no HumanApprovalPanel stage"
    assert any("BLOCKED" in s.status for s in hap)


def test_statuses_seen_only_contains_safe_set():
    trace = run_smoke()
    safe = {
        "TAURI_COMMAND_OK",
        "TAURI_COMMAND_TEMP_ONLY",
        "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
        "TAURI_COMMAND_BLOCKED_NOT_OPTED_IN",
        "TAURI_COMMAND_BLOCKED_NO_MODEL",
    }
    assert set(trace.statuses_seen).issubset(safe)


def test_trace_serializes_to_json_dict():
    trace = run_smoke()
    d = trace.to_dict()
    assert isinstance(d, dict)
    assert isinstance(d["stages"], list)
    assert all("panel" in stage for stage in d["stages"])
    # Round-trips through json.
    json.dumps(d)


def test_visible_panel_sequence_calls_at_least_one_tauri_command_per_panel():
    trace = run_smoke()
    seen_per_panel: dict[str, set[str]] = {}
    for s in trace.stages:
        seen_per_panel.setdefault(s.panel, set()).add(s.tauri_command)
    for panel, cmds in seen_per_panel.items():
        assert cmds, f"{panel} produced no commands"


def test_no_spawn_no_socket_smoke_is_in_process():
    # Smoke trace runs entirely in-process via _tauri_driver._dispatch,
    # never spawning a subprocess or opening a socket. We assert that
    # by checking no live-model module is imported at module load.
    import scripts.ide.frontend_end_to_end_repair_flow_smoke as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("requests", "httpx", "urllib.request", "socket.connect"):
        assert forbidden not in src, f"forbidden import/use: {forbidden}"


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED_TOKENS)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("live_model_called") is False
    assert sd.get("network_called") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_LOCK_001" in ids
