"""Tests for FRONTEND_COMMAND_INVOKE_CLIENT_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT = _REPO_ROOT / "frontend" / "src" / "lib" / "ide-invoke-client.ts"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_COMMAND_INVOKE_CLIENT_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_command_invoke_client"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(
    {
        "FRONTEND_COMMAND_INVOKE_CLIENT_READY",
        "FRONTEND_COMMAND_INVOKE_CLIENT_BLOCKED_TAURI_UNAVAILABLE",
        "FRONTEND_COMMAND_ERROR_VISIBLE",
    }
)


def test_client_exists():
    assert CLIENT.is_file()


def test_status_tokens_exact():
    src = CLIENT.read_text(encoding="utf-8")
    m = re.search(
        r"FRONTEND_COMMAND_INVOKE_CLIENT_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const",
        src,
    )
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_client_exposes_typed_args_for_every_command():
    src = CLIENT.read_text(encoding="utf-8")
    # Each command must appear in the discriminated union.
    for cmd in (
        "open_workspace",
        "get_workspace_status",
        "get_model_route_status",
        "diagnose_dry_run",
        "diagnose_live_opt_in",
        "generate_patch_plan",
        "verify_temp_patch",
        "get_human_approval_packet",
        "source_apply_dry_run",
        "get_repair_flow_state",
    ):
        assert f'command: "{cmd}";' in src, f"missing typed arm: {cmd}"


def test_client_offers_mock_transport():
    src = CLIENT.read_text(encoding="utf-8")
    assert "makeMockTransport" in src
    assert "IdeInvokeTransport" in src
    assert "runtimeReady" in src


def test_client_uses_locked_underlying_wrapper():
    src = CLIENT.read_text(encoding="utf-8")
    # Must build on ide-repair-api.ts (the already-locked wrapper).
    assert 'from "./ide-repair-api"' in src
    assert "invokeIdeCommand" in src
    assert "tauriRuntimePresent" in src


def test_client_does_not_introduce_source_mutation_or_training_flags():
    src = CLIENT.read_text(encoding="utf-8")
    # No new code path may set these to true.
    for forbidden in (
        "source_mutation_authorized: true",
        "training_eligible: true",
    ):
        assert forbidden not in src, f"forbidden literal: {forbidden}"


def test_client_blocks_unknown_command_with_safe_response():
    src = CLIENT.read_text(encoding="utf-8")
    assert "TAURI_COMMAND_BLOCKED_UNKNOWN" in src
    assert "rejected unknown command" in src


def test_client_surfaces_tauri_unavailable_token_when_runtime_missing():
    src = CLIENT.read_text(encoding="utf-8")
    assert "FRONTEND_COMMAND_INVOKE_CLIENT_BLOCKED_TAURI_UNAVAILABLE" in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_COMMAND_INVOKE_CLIENT_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("live_model_called") is False
    assert sd.get("network_provider_admitted") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_COMMAND_INVOKE_CLIENT_LOCK_001" in ids
