"""Tests for FRONTEND_REPAIR_PANEL_SHELL_LOCK_001.

Validates the shell .tsx file and the API library shape without running
vitest (so the Python test suite alone is the proof). Inspects:

  * shell renders the 9 required sections
  * blocked states are visible
  * source mutation blocked status is visible
  * training eligibility false is visible
  * approval required is visible
  * forbidden hype language is absent
  * API library exports the IDE_REPAIR_STATUS_TOKENS closed set
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SHELL = _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair" / "RepairPanelShell.tsx"
API = _REPO_ROOT / "frontend" / "src" / "lib" / "ide-repair-api.ts"
PAGE = _REPO_ROOT / "frontend" / "src" / "app" / "ide-repair" / "page.tsx"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_REPAIR_PANEL_SHELL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_repair_panel_shell"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


REQUIRED_SECTIONS = (
    "Workspace",
    "Verifier",
    "Model Route",
    "Diagnosis",
    "Patch Plan",
    "Temp Verification",
    "Human Approval",
    "Evidence",
    "Risk Warnings",
)


REPAIR_PANEL_STATUS_TOKENS = frozenset(
    {
        "REPAIR_PANEL_SHELL_READY",
        "REPAIR_PANEL_BLOCKED_FRONTEND_MISSING",
        "REPAIR_PANEL_SOURCE_MUTATION_BLOCKED_VISIBLE",
        "REPAIR_PANEL_RISK_WARNINGS_VISIBLE",
    }
)


FORBIDDEN_HYPE = (
    "always correct",
    "guaranteed to work",
    "risk-free",
    "trust the AI",
    "blindly approve",
    "no need to read",
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_shell_file_exists():
    assert SHELL.is_file()


def test_shell_lists_all_required_sections():
    src = _read(SHELL)
    for section in REQUIRED_SECTIONS:
        assert f'"{section}"' in src, f"Section {section!r} missing from shell"


def test_shell_status_token_constant_matches_lock_set():
    src = _read(SHELL)
    m = re.search(r"REPAIR_PANEL_STATUS_TOKENS\s*=\s*\[([^\]]+)\]", src)
    assert m, "REPAIR_PANEL_STATUS_TOKENS constant missing"
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == REPAIR_PANEL_STATUS_TOKENS


def test_shell_renders_source_mutation_blocked_banner():
    src = _read(SHELL)
    # The exact data-testid we anchor on.
    assert "repair-shell-source-mutation-blocked" in src
    assert "Source mutation is BLOCKED" in src


def test_shell_renders_training_eligibility_false():
    src = _read(SHELL)
    assert "repair-shell-training-eligibility" in src
    assert "Training eligibility" in src
    assert "False" in src


def test_shell_renders_approval_required():
    src = _read(SHELL)
    assert "repair-shell-approval-required" in src
    assert "Approval" in src


def test_shell_has_no_forbidden_hype():
    src = _read(SHELL).lower()
    for phrase in FORBIDDEN_HYPE:
        assert phrase.lower() not in src, f"Forbidden phrase in shell: {phrase}"


def test_shell_has_no_source_apply_button():
    """The shell rung must not introduce a real-source-apply control."""
    src = _read(SHELL)
    # Heuristic: no button labelled apply/commit/write to source.
    for needle in ("Apply to Source", "Commit to Source", "Write to Source"):
        assert needle not in src, f"Forbidden control: {needle}"


# ---------------------------------------------------------------------------
# API library
# ---------------------------------------------------------------------------


def test_api_lib_exists():
    assert API.is_file()


def test_api_lib_declares_all_commands():
    src = _read(API)
    m = re.search(r"IDE_REPAIR_COMMANDS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m, "IDE_REPAIR_COMMANDS const missing"
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    expected = {
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
    }
    assert declared == expected


def test_api_lib_refuses_source_mutation_from_backend():
    """If the backend ever returns source_mutation_authorized=true, the
    frontend wrapper must drop it back to false."""
    src = _read(API)
    assert "frontend refused source_mutation_authorized=true" in src


def test_api_lib_refuses_training_eligible_from_backend():
    src = _read(API)
    assert "frontend refused training_eligible=true" in src


def test_api_lib_status_tokens_include_blocked_set():
    src = _read(API)
    m = re.search(r"IDE_REPAIR_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    must_include = {
        "TAURI_COMMAND_OK",
        "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
        "TAURI_COMMAND_BLOCKED_NOT_OPTED_IN",
        "TAURI_COMMAND_BLOCKED_NO_MODEL",
        "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
    }
    assert must_include.issubset(declared)


def test_page_route_exists():
    assert PAGE.is_file()
    src = _read(PAGE)
    assert "RepairPanelShell" in src


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_REPAIR_PANEL_SHELL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(REPAIR_PANEL_STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_REPAIR_PANEL_SHELL_LOCK_001" in ids
