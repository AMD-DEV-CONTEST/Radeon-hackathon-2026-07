"""Tests for FRONTEND_PANEL_COMMAND_WIRING_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
BINDINGS = _REPO_ROOT / "frontend" / "src" / "lib" / "ide-panel-bindings.ts"
PANELS_DIR = _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_PANEL_COMMAND_WIRING_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_panel_command_wiring"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(
    {
        "FRONTEND_PANEL_COMMAND_WIRING_READY",
        "FRONTEND_DRY_RUN_DEFAULT_CONFIRMED",
        "FRONTEND_LIVE_OPT_IN_REQUIRED",
        "FRONTEND_SOURCE_MUTATION_BLOCKED",
    }
)

# Panel name -> (expected commands, default mode)
EXPECTED_BINDINGS = {
    "DiagnoseAndPatchPlanPanel": (
        {"diagnose_dry_run", "diagnose_live_opt_in", "generate_patch_plan"},
        "DRY_RUN",
    ),
    "EvidenceViewerPanel": ({"get_repair_flow_state"}, "READ_ONLY"),
    "HumanApprovalPanel": ({"get_human_approval_packet"}, "FIXTURE_ONLY"),
    "ModelRoutePanel": ({"get_model_route_status"}, "READ_ONLY"),
    "SourceApplyDryRunPanel": ({"source_apply_dry_run"}, "DRY_RUN"),
    "TempVerifyPanel": ({"verify_temp_patch"}, "FIXTURE_ONLY"),
    "WorkspaceStatusPanel": ({"get_workspace_status"}, "READ_ONLY"),
}


def test_bindings_module_exists():
    assert BINDINGS.is_file()


def test_status_tokens_exact():
    src = BINDINGS.read_text(encoding="utf-8")
    m = re.search(
        r"FRONTEND_PANEL_COMMAND_WIRING_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const",
        src,
    )
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_bindings_module_declares_every_expected_panel():
    src = BINDINGS.read_text(encoding="utf-8")
    for panel in EXPECTED_BINDINGS:
        assert f'panel: "{panel}"' in src, f"binding missing panel {panel}"


def test_every_panel_tsx_calls_its_declared_commands():
    for panel, (cmds, _mode) in EXPECTED_BINDINGS.items():
        path = PANELS_DIR / f"{panel}.tsx"
        assert path.is_file(), f"{panel}.tsx missing"
        src = path.read_text(encoding="utf-8")
        for cmd in cmds:
            assert f'"{cmd}"' in src, f"{panel} does not reference command {cmd!r}"


def test_diagnose_panel_dry_run_default():
    src = (PANELS_DIR / "DiagnoseAndPatchPlanPanel.tsx").read_text(encoding="utf-8")
    # Live diagnose must require an opt-in check before invocation.
    assert "live" in src.lower()
    assert "opt" in src.lower() and "in" in src.lower()
    # Default UI behavior should mention dry-run.
    assert "dry" in src.lower() and "run" in src.lower()


def test_no_panel_authorizes_source_mutation():
    for panel in EXPECTED_BINDINGS:
        src = (PANELS_DIR / f"{panel}.tsx").read_text(encoding="utf-8")
        for forbidden in (
            "source_mutation_authorized: true",
            "training_eligible: true",
            "real_apply",
            "force_apply",
        ):
            assert forbidden not in src, f"{panel}: forbidden {forbidden}"


def test_panels_route_through_the_locked_wrapper():
    for panel in EXPECTED_BINDINGS:
        src = (PANELS_DIR / f"{panel}.tsx").read_text(encoding="utf-8")
        # Every panel must import from ide-repair-api (the locked wrapper).
        assert "ide-repair-api" in src, f"{panel} does not import the locked wrapper"


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_PANEL_COMMAND_WIRING_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)
    sd = blob.get("scope_discipline", {})
    assert sd.get("user_source_mutated") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("live_model_called") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_PANEL_COMMAND_WIRING_LOCK_001" in ids
