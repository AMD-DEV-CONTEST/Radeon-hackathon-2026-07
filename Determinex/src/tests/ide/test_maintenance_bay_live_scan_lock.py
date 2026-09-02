"""Tests for DETERMINEX_MAINTENANCE_BAY_LIVE_SECURITY_SCAN_LOCK_001.

Live wiring for Maintenance Bay: composes the EXISTING scripts/security/*.py
scanners (secret_scan, dependency_scan, verify_lockfiles, verify_installed,
license_scan, container_scan) via security_gate.run_all() into one read-only advisory
result. The count is deliberately not written down here -- see expected_gates(). No new scanner logic
was written -- this rung is wiring, not invention.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

bcs = importlib.import_module("ide.backend_command_surface")
td = importlib.import_module("ide._tauri_driver")

LOCK_PATH = (
    _REPO_ROOT
    / "locks"
    / "sentinel"
    / "DETERMINEX_MAINTENANCE_BAY_LIVE_SECURITY_SCAN_LOCK_001.json"
)
EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "determinex_maintenance_bay_live_security_scan"
)
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
PANEL_PATH = (
    _REPO_ROOT / "frontend" / "src" / "components" / "ide-product-shell" / "MaintenanceBayPanel.tsx"
)
BRIDGE_RS = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "ide_repair_bridge.rs"
LIB_RS = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "lib.rs"

# The gates the Maintenance Bay must ALWAYS compose. A floor, not the full list:
# removing any of these is a real regression and must fail here.
REQUIRED_GATES = (
    "secret_scan",
    "dependency_scan",
    "verify_lockfiles",
    "license_scan",
    "container_scan",
)


# These tests run `security_gate.run_all()` for real, and two of its six scanners write to a
# COMMITTED path by design. The redirect that stops them overwriting that evidence lives in
# tests/conftest.py (`_scanner_output_off_tracked_paths`) rather than here: it is a property of the
# suite, not of this file. It was first fixed here, and the files came back dirty from a different
# test on the next full run.


def expected_gates() -> set[str]:
    """Derived from security_gate.GATES, not hand-maintained.

    This was a hardcoded 5-tuple and went red the moment a sixth gate
    (`verify_installed`, 2026-07-28) was added -- a list-drift failure, not a
    regression in what it guards. Deriving the full set means adding a gate cannot
    break this lock, while REQUIRED_GATES above still fails if one is dropped.
    """
    sys.path.insert(0, str(_REPO_ROOT / "scripts" / "security"))
    security_gate = importlib.import_module("security_gate")
    return {name for name, _fn in security_gate.GATES}


def test_command_registered_in_full_surface():
    assert "run_maintenance_bay_scan" in bcs.commands()


def test_command_deliberately_excluded_from_frozen_read_only_set():
    assert "run_maintenance_bay_scan" not in bcs.UNIFIED_PRODUCT_READ_ONLY_COMMANDS


def test_command_surface_runs_all_real_gates():
    """A REAL correctness check, not shape-only: the actual security_gate.run_all()
    composition, not a mock. Confirms every gate security_gate defines ran (or reports
    why one didn't)."""
    surface = bcs.IDEBackendCommandSurface()
    r = surface.call("run_maintenance_bay_scan")
    assert r.status == "IDE_COMMAND_OK"
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    if "scan_error" in r.payload:
        # Environment-dependent (e.g. a scanner script moved) -- must fail loud, not
        # silently claim a pass. Never a crash out of the command surface itself.
        assert r.payload.get("overall_passed") is None
        return
    gate_names = {g["gate"] for g in r.payload["gates"]}
    assert gate_names == expected_gates(), (
        "the command surface did not report every gate security_gate defines"
    )
    missing = set(REQUIRED_GATES) - gate_names
    assert not missing, f"a required gate was dropped from the composition: {sorted(missing)}"
    assert isinstance(r.payload["overall_passed"], bool)


def test_never_claims_a_pass_when_a_gate_crashes():
    """security_gate.run_all() itself already guards this (GATE CRASHED -> passed=False);
    this test proves the command surface doesn't unwrap/lose that guarantee."""
    surface = bcs.IDEBackendCommandSurface()
    r = surface.call("run_maintenance_bay_scan")
    if "scan_error" in r.payload:
        return
    for gate in r.payload["gates"]:
        if "CRASHED" in gate["detail"]:
            assert gate["passed"] is False


def test_tauri_driver_dispatches_new_command():
    res = td._dispatch("run_maintenance_bay_scan", {})
    assert res["status"] == "TAURI_COMMAND_OK"
    assert res["source_mutation_authorized"] is False
    assert res["training_eligible"] is False


def test_tauri_driver_did_not_remove_get_workflow_state():
    res = td._dispatch("get_maintenance_bay_workflow_state", {})
    assert res["status"] == "TAURI_COMMAND_OK"


def test_rust_command_function_declared():
    src = BRIDGE_RS.read_text(encoding="utf-8")
    assert "pub fn run_maintenance_bay_scan(" in src


def test_rust_command_registered_in_generate_handler():
    src = LIB_RS.read_text(encoding="utf-8")
    assert "ide_repair_bridge::run_maintenance_bay_scan," in src


def test_rust_command_excluded_from_frozen_unified_product_list():
    import re

    src = BRIDGE_RS.read_text(encoding="utf-8")
    m = re.search(
        r"UNIFIED_PRODUCT_READ_ONLY_COMMANDS\s*:\s*&\[&str\]\s*=\s*&\[(.+?)\];", src, re.DOTALL
    )
    assert m
    declared = re.findall(r'"([^"]+)"', m.group(1))
    assert "run_maintenance_bay_scan" not in declared


def test_panel_invokes_the_new_command():
    src = PANEL_PATH.read_text(encoding="utf-8")
    assert '"run_maintenance_bay_scan"' in src
    assert 'data-testid="maintenance-bay-run-scan"' in src


def test_panel_not_auto_fetched_on_mount():
    """The scan is explicit opt-in (button click), not wired into the useEffect that
    fires on mount -- it can take several seconds (pip-audit over the whole env)."""
    import re

    src = PANEL_PATH.read_text(encoding="utf-8")
    # Whitespace-tolerant: this exact construct is legitimately reformatted
    # to multi-line by Prettier (`printWidth`-driven), which doesn't change
    # its meaning -- an exact single-line match was fragile against nothing
    # but formatting. Found live 2026-07-19 after a repo-wide `prettier
    # --write .` pass (frontend/eslint.config.mjs's fix, unrelated) broke
    # this assertion despite the actual effect body being unchanged.
    m = re.search(
        r"React\.useEffect\(\(\)\s*=>\s*\{\s*void refresh\(\);\s*\},\s*\[refresh\]\);", src
    )
    assert m, "expected the mount effect to call only refresh(), not runScan()"
    for m in re.finditer(r"React\.useEffect\(([\s\S]*?)\}, \[[^\]]*\]\);", src):
        assert "runScan" not in m.group(1), "runScan must not be called from any useEffect"
    assert "onClick={() => void runScan()}" in src


def test_panel_still_non_authorizing_after_wiring():
    src = PANEL_PATH.read_text(encoding="utf-8").lower()
    for phrase in (
        "dependency updated!",
        "all dependencies up to date",
        "production-ready",
        "patch applied",
        "now fixed",
        "source mutation authorized",
    ):
        assert phrase not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_MAINTENANCE_BAY_LIVE_SECURITY_SCAN_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False
    assert sd["update_applied"] is False


def test_evidence_artifact_present():
    assert sorted(EVIDENCE_DIR.glob("run_*.json"))


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_MAINTENANCE_BAY_LIVE_SECURITY_SCAN_LOCK_001" in ids
