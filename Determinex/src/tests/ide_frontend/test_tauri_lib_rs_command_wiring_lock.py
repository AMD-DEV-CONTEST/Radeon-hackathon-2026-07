"""Tests for TAURI_LIB_RS_COMMAND_WIRING_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_RS = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "lib.rs"
BRIDGE_RS = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "ide_repair_bridge.rs"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "TAURI_LIB_RS_COMMAND_WIRING_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "tauri_lib_rs_command_wiring"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


EXPECTED_COMMANDS = (
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
    "generate_llm_program_advisory",
    "preview_idea_oracle",
    "build_idea",
    "repair_diagnose",
    "get_governance_status",
)

UNIFIED_PRODUCT_COMMANDS = (
    "get_unified_product_navigation_model",
    "get_idea_lab_workflow_state",
    "get_repo_clinic_workflow_state",
    "get_maintenance_bay_workflow_state",
    "get_learning_studio_workflow_state",
    "get_proof_operator_center_state",
    "get_user_level_teaching_windows",
    "get_unified_splash_demo_spec",
    "get_idea_lab_verified_demo_status",
    "get_repo_clinic_verified_demo_status",
    "get_maintenance_bay_verified_demo_status",
    "get_learning_studio_verified_demo_status",
    "get_proof_operator_center_milestone_dashboard_status",
)

STATUS_TOKENS = frozenset(
    {
        "TAURI_LIB_RS_COMMAND_WIRING_READY",
        "TAURI_LIB_RS_COMMAND_WIRING_BLOCKED_NO_ENTRYPOINT",
        "TAURI_LIB_RS_COMMAND_WIRING_BLOCKED_COMMAND_MISMATCH",
        "TAURI_LIB_RS_SOURCE_MUTATION_BLOCKED",
    }
)


def test_lib_rs_exists():
    assert LIB_RS.is_file()


def test_lib_rs_declares_bridge_module():
    src = LIB_RS.read_text(encoding="utf-8")
    assert "mod ide_repair_bridge;" in src


def test_lib_rs_registers_every_bridge_command():
    src = LIB_RS.read_text(encoding="utf-8")
    # Find the generate_handler! block.
    m = re.search(
        r"\.invoke_handler\s*\(\s*tauri::generate_handler!\s*\[(.+?)\]\s*\)",
        src,
        re.DOTALL,
    )
    assert m, "could not locate tauri::generate_handler! block"
    block = m.group(1)
    for cmd in EXPECTED_COMMANDS:
        assert f"ide_repair_bridge::{cmd}" in block, f"missing wiring: {cmd}"


def test_bridge_rs_command_list_matches_lib_rs_wiring():
    # bridge declares the const IDE_REPAIR_COMMANDS — that list must match.
    src = BRIDGE_RS.read_text(encoding="utf-8")
    m = re.search(r"IDE_REPAIR_COMMANDS\s*:\s*&\[&str\]\s*=\s*&\[(.+?)\];", src, re.DOTALL)
    assert m
    declared = tuple(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == EXPECTED_COMMANDS


def test_unified_product_read_only_commands_are_wired():
    src = LIB_RS.read_text(encoding="utf-8")
    m = re.search(
        r"\.invoke_handler\s*\(\s*tauri::generate_handler!\s*\[(.+?)\]\s*\)",
        src,
        re.DOTALL,
    )
    assert m, "could not locate tauri::generate_handler! block"
    block = m.group(1)
    for cmd in UNIFIED_PRODUCT_COMMANDS:
        assert f"ide_repair_bridge::{cmd}" in block, f"missing unified-product wiring: {cmd}"


def test_bridge_declares_unified_product_read_only_command_list():
    src = BRIDGE_RS.read_text(encoding="utf-8")
    m = re.search(
        r"UNIFIED_PRODUCT_READ_ONLY_COMMANDS\s*:\s*&\[&str\]\s*=\s*&\[(.+?)\];",
        src,
        re.DOTALL,
    )
    assert m
    declared = tuple(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == UNIFIED_PRODUCT_COMMANDS


def test_bridge_rs_keeps_safety_invariants():
    src = BRIDGE_RS.read_text(encoding="utf-8")
    # Bridge struct hardcodes the safe defaults — we assert by source.
    assert "source_mutation_authorized: bool" in src
    assert "training_eligible: bool" in src
    # Reject blanket re-enabling.
    for forbidden in (
        # No #[tauri::command] that returns a raw String diff body
        # would constitute a real apply. The current bridge wraps everything.
        "real_apply",
        "force_apply",
        "approve_apply",
    ):
        assert forbidden not in src, f"forbidden helper: {forbidden}"


def test_lib_rs_does_not_introduce_new_network_or_docker_calls():
    src = LIB_RS.read_text(encoding="utf-8")
    # The bridge wiring should not have introduced anything that looks like
    # a network call. We allow existing Ollama probe / model puller commands
    # because they predate this lock.
    bridge_lines = [ln for ln in src.splitlines() if "ide_repair_bridge::" in ln]
    joined = "\n".join(bridge_lines)
    for forbidden in ("reqwest", "hyper", "tonic", "http://", "https://"):
        assert forbidden not in joined, f"forbidden in bridge wiring: {forbidden}"


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "TAURI_LIB_RS_COMMAND_WIRING_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("network_provider_admitted") is False
    assert sd.get("codex_lane_files_touched") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "TAURI_LIB_RS_COMMAND_WIRING_LOCK_001" in ids


def test_cargo_check_record_present_in_evidence():
    # The evidence artifact must record the cargo check result.
    artifact = sorted(EVIDENCE_DIR.glob("run_*.json"))[-1]
    blob = json.loads(artifact.read_text(encoding="utf-8"))
    assert blob.get("cargo_check", {}).get("status") in {"PASSED", "PASSED_WITH_WARNINGS"}
