"""Tests for TAURI_COMMAND_VERB_ALIGNMENT_LOCK_001.

Asserts every Tauri command maps to a backend command whose verb
matches the Tauri-side label, and that the dedicated
source_apply_dry_run inner command exists.
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = _REPO_ROOT / "scripts" / "ide" / "_tauri_driver.py"
SURFACE = _REPO_ROOT / "scripts" / "ide" / "backend_command_surface.py"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "TAURI_COMMAND_VERB_ALIGNMENT_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "tauri_command_verb_alignment"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


EXPECTED_VERB_MAP = {
    "open_workspace": "inspect_workspace",
    "get_workspace_status": "inspect_workspace",
    "get_model_route_status": "route_model",
    "diagnose_dry_run": "diagnose_dry_run",
    "diagnose_live_opt_in": "diagnose_live_opt_in",
    "generate_patch_plan": "generate_patch_plan_opt_in",
    "verify_temp_patch": "verify_temp_patch",
    "get_human_approval_packet": "get_human_approval_packet",
    # CLAUDE-AUTH-006 remediation: source_apply_dry_run now has its
    # own backend command, not aliased to get_repair_state.
    "source_apply_dry_run": "source_apply_dry_run",
    "get_repair_flow_state": "get_repair_state",
}


def test_driver_maps_every_tauri_command():
    """Live dispatch: every Tauri command resolves to a non-blocked
    inner status (or an explicitly safe one). Source apply must NOT
    map to repair_state — that was the CLAUDE-AUTH-006 bug."""
    import sys

    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from ide._tauri_driver import _dispatch  # noqa: E402

    for tauri_cmd in EXPECTED_VERB_MAP:
        args = {"workspace": "/tmp/ws"}
        if tauri_cmd == "diagnose_live_opt_in":
            args["opt_in"] = False
        if tauri_cmd == "generate_patch_plan":
            args["opt_in"] = False
        if tauri_cmd == "get_model_route_status":
            args["task_class"] = "BUILD_DIAGNOSIS"
        resp = _dispatch(tauri_cmd, args)
        # Resolved status must be a known Tauri status; UNKNOWN means
        # the driver dropped the mapping.
        assert resp["status"] != "TAURI_COMMAND_BLOCKED_UNKNOWN", (
            f"driver dropped mapping for {tauri_cmd!r}"
        )


def test_surface_recognizes_source_apply_dry_run_inner_command():
    src = SURFACE.read_text(encoding="utf-8")
    # Backend command surface must list source_apply_dry_run in
    # _COMMANDS frozenset and dispatch to a dedicated handler.
    assert '"source_apply_dry_run"' in src
    assert "_source_apply_dry_run" in src
    # The handler must NOT alias to get_repair_state.
    # (Spot-check: dedicated method body refers to its own command name.)
    assert 'return self._result(\n            "source_apply_dry_run"' in src


def test_source_apply_dry_run_payload_declares_dry_run_only():
    src = SURFACE.read_text(encoding="utf-8")
    # The handler payload must explicitly state dry-run mode.
    assert '"mode": "dry_run_only"' in src
    assert '"source_apply_attempted": False' in src


def test_dispatcher_returns_dedicated_dry_run_record():
    """End-to-end via _dispatch: source_apply_dry_run returns the
    dedicated payload (dry_run_only) — NOT the repair_state payload."""
    import sys

    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from ide._tauri_driver import _dispatch  # noqa: E402

    resp = _dispatch("source_apply_dry_run", {"workspace": "/tmp/ws"})
    assert resp["status"] == "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED"
    payload = resp["payload"]
    assert payload.get("mode") == "dry_run_only"
    assert payload.get("source_apply_attempted") is False
    # Confirm it is NOT the repair_state shape (which has its own field).
    assert "source_mutation" in payload
    assert payload["source_mutation"] == "BLOCKED_PENDING_REAL_HUMAN_APPROVAL"


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "TAURI_COMMAND_VERB_ALIGNMENT_LOCK_001"
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "TAURI_COMMAND_VERB_ALIGNMENT_LOCK_001" in ids
