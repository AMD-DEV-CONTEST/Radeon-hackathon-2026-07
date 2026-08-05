"""Tests for FRONTEND_WORKSPACE_STATUS_PANEL_LOCK_001."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

PANEL = _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair" / "WorkspaceStatusPanel.tsx"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_WORKSPACE_STATUS_PANEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_workspace_status_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(
    {
        "WORKSPACE_STATUS_PANEL_READY",
        "WORKSPACE_STATUS_UNSUPPORTED_VISIBLE",
        "WORKSPACE_STATUS_VERIFIER_MISSING_VISIBLE",
        "WORKSPACE_STATUS_SOURCE_UNCHANGED",
    }
)


def test_panel_exists():
    assert PANEL.is_file()


def test_panel_status_tokens_constant_exact():
    src = PANEL.read_text(encoding="utf-8")
    import re

    m = re.search(r"WORKSPACE_STATUS_PANEL_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_panel_calls_get_workspace_status():
    src = PANEL.read_text(encoding="utf-8")
    assert '"get_workspace_status"' in src


def test_panel_renders_adapter_and_supported_fields():
    src = PANEL.read_text(encoding="utf-8")
    for needle in (
        'data-testid="workspace-status-adapter"',
        'data-testid="workspace-status-supported"',
        'data-testid="workspace-status-verifier"',
        'data-testid="workspace-status-path"',
    ):
        assert needle in src


def test_panel_says_source_unchanged():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="workspace-source-unchanged-note"' in src
    assert "files were not modified" in src.lower()


def test_panel_renders_evidence_refs_when_present():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="workspace-status-evidence-refs"' in src


def test_panel_has_no_source_apply_or_write_controls():
    src = PANEL.read_text(encoding="utf-8")
    for needle in ("Apply to Source", "Commit", "Write to Source", "source_apply"):
        assert needle not in src, f"Forbidden control: {needle}"


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_WORKSPACE_STATUS_PANEL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_WORKSPACE_STATUS_PANEL_LOCK_001" in ids
