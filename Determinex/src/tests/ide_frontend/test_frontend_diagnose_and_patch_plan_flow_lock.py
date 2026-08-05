"""Tests for FRONTEND_DIAGNOSE_AND_PATCH_PLAN_FLOW_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
PANEL = (
    _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair" / "DiagnoseAndPatchPlanPanel.tsx"
)
LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_DIAGNOSE_AND_PATCH_PLAN_FLOW_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_diagnose_and_patch_plan_flow"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(
    {
        "FRONTEND_DIAGNOSE_DRY_RUN_READY",
        "FRONTEND_LIVE_DIAGNOSE_OPT_IN_REQUIRED",
        "FRONTEND_PATCH_PLAN_QUARANTINED",
        "FRONTEND_PATCH_PLAN_SOURCE_UNCHANGED",
    }
)


def test_panel_exists():
    assert PANEL.is_file()


def test_status_tokens_exact():
    src = PANEL.read_text(encoding="utf-8")
    m = re.search(r"DIAGNOSE_PATCH_PLAN_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_diagnose_dry_run_button_exists():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="diagnose-dry-run-button"' in src
    assert '"diagnose_dry_run"' in src


def test_diagnose_live_opt_in_requires_checkbox():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="diagnose-live-opt-in-checkbox"' in src
    assert 'data-testid="diagnose-live-button"' in src
    # The live button must be disabled when opt-in is false.
    assert "disabled={!liveOptIn}" in src


def test_patch_plan_requires_explicit_opt_in():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="patch-plan-opt-in-checkbox"' in src
    assert 'data-testid="patch-plan-button"' in src
    assert "disabled={!planOptIn}" in src


def test_advisory_and_quarantine_notes_present():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="diagnose-advisory-note"' in src
    assert "advisory" in src.lower()
    assert 'data-testid="patch-plan-quarantined-note"' in src
    assert "quarantined" in src.lower()
    assert "not modified" in src.lower()


def test_panel_invokes_correct_commands():
    src = PANEL.read_text(encoding="utf-8")
    assert '"diagnose_live_opt_in"' in src
    assert '"generate_patch_plan"' in src


def test_panel_does_not_apply_patch():
    src = PANEL.read_text(encoding="utf-8")
    for n in ("Apply to Source", "Commit", "source_apply", "applyToSource"):
        assert n not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_DIAGNOSE_AND_PATCH_PLAN_FLOW_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_DIAGNOSE_AND_PATCH_PLAN_FLOW_LOCK_001" in ids
