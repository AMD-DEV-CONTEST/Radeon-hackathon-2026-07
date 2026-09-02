"""Tests for FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_LOCK_001."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ide.frontend_live_diagnose_opt_in_smoke import (
    FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_TOKENS,
    FrontendLiveDiagnoseSmokeTrace,
    run_smoke,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_live_diagnose_opt_in_smoke"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED_TOKENS = frozenset(
    {
        "FRONTEND_LIVE_DIAGNOSE_SMOKE_READY",
        "FRONTEND_LIVE_DIAGNOSE_BLOCKED_NO_PROVIDER",
        "FRONTEND_LIVE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
        "FRONTEND_LIVE_DIAGNOSE_ADVISORY_ONLY",
        "FRONTEND_LIVE_DIAGNOSE_NO_PATCH_GENERATED",
        "FRONTEND_LIVE_DIAGNOSE_NO_SOURCE_MUTATION",
        "FRONTEND_LIVE_DIAGNOSE_NO_TRAINING_ROW",
    }
)


def test_status_tokens_exact():
    assert set(FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_TOKENS) == EXPECTED_TOKENS


def test_dry_run_path_succeeds():
    t = run_smoke()
    assert t.dry_run_stage.tauri_command == "diagnose_dry_run"
    assert t.dry_run_stage.status in {"TAURI_COMMAND_OK", "TAURI_COMMAND_TEMP_ONLY"}


def test_live_without_opt_in_is_blocked():
    t = run_smoke()
    assert t.not_opted_in_stage.tauri_command == "diagnose_live_opt_in"
    assert "BLOCKED" in t.not_opted_in_stage.status
    assert "NOT_OPTED_IN" in t.not_opted_in_stage.status


def test_live_with_opt_in_but_no_provider_is_blocked(monkeypatch):
    import ide._tauri_driver as td

    monkeypatch.setattr(td, "_build_local_config", lambda *a: None)
    t = run_smoke()
    assert t.no_provider_stage.tauri_command == "diagnose_live_opt_in"
    assert "BLOCKED" in t.no_provider_stage.status
    assert "NO_MODEL" in t.no_provider_stage.status


def test_advisory_stage_keeps_status_safe():
    t = run_smoke()
    # The advisory-only stage must not have any status that implies real
    # apply or trusted output.
    assert "APPROVED" not in t.advisory_stage.status
    assert "APPLIED" not in t.advisory_stage.status


def test_trace_invariants():
    t = run_smoke()
    assert isinstance(t, FrontendLiveDiagnoseSmokeTrace)
    assert t.output_advisory_only is True
    assert t.patch_generated is False
    assert t.source_mutated is False
    assert t.training_row_written is False


def test_trace_serializes_with_safe_flags():
    t = run_smoke()
    d = t.to_dict()
    json.dumps(d)
    assert d["patch_generated"] is False
    assert d["source_mutated"] is False
    assert d["training_row_written"] is False


def test_smoke_module_does_not_open_network_or_spawn_subprocess():
    import scripts.ide.frontend_live_diagnose_opt_in_smoke as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "requests",
        "httpx",
        "urllib.request",
        "socket.connect",
        "subprocess.Popen",
        "subprocess.run",
    ):
        assert forbidden not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED_TOKENS)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_row_written") is False
    assert sd.get("patch_generated") is False
    assert sd.get("network_called") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_LOCK_001" in ids
