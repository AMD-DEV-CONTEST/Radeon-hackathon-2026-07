"""Tests for FRONTEND_SOURCE_APPLY_DRY_RUN_PANEL_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
PANEL = _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair" / "SourceApplyDryRunPanel.tsx"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_SOURCE_APPLY_DRY_RUN_PANEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_source_apply_dry_run_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(
    {
        "SOURCE_APPLY_DRY_RUN_PANEL_READY",
        "SOURCE_APPLY_BLOCKED_VISIBLE",
        "SOURCE_APPLY_SOURCE_UNCHANGED_VISIBLE",
        "SOURCE_APPLY_REAL_WRITE_DISABLED",
    }
)


def test_panel_exists():
    assert PANEL.is_file()


def test_status_tokens_exact():
    src = PANEL.read_text(encoding="utf-8")
    m = re.search(r"SOURCE_APPLY_DRY_RUN_PANEL_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_calls_source_apply_dry_run():
    src = PANEL.read_text(encoding="utf-8")
    assert '"source_apply_dry_run"' in src


def test_real_write_disabled_note_present():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="source-apply-real-write-disabled-note"' in src
    assert "Real source mutation is disabled" in src


def test_source_unchanged_note():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="source-apply-source-unchanged-note"' in src
    assert "unchanged" in src.lower()


def test_blocked_note_present_path():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="source-apply-blocked-note"' in src


def test_panel_has_no_real_apply_button():
    src = PANEL.read_text(encoding="utf-8")
    # Heuristic: no button literally writing source.
    for needle in (
        "Apply to Source",
        "Commit to Source",
        "Write changes",
        "applyToSource",
        "<button.*Apply.*Source",
    ):
        assert not re.search(needle, src), f"Forbidden control: {needle}"


def test_lock_manifest_exists():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_SOURCE_APPLY_DRY_RUN_PANEL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_SOURCE_APPLY_DRY_RUN_PANEL_LOCK_001" in ids
