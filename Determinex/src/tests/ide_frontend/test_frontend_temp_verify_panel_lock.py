"""Tests for FRONTEND_TEMP_VERIFY_PANEL_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
PANEL = _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair" / "TempVerifyPanel.tsx"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_TEMP_VERIFY_PANEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_temp_verify_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(
    {
        "TEMP_VERIFY_PANEL_READY",
        "TEMP_VERIFY_FAILED_VISIBLE",
        "TEMP_VERIFY_PASSED_TEMP_ONLY_VISIBLE",
        "TEMP_VERIFY_HUMAN_APPROVAL_REQUIRED_VISIBLE",
    }
)


def test_panel_exists():
    assert PANEL.is_file()


def test_status_tokens_exact():
    src = PANEL.read_text(encoding="utf-8")
    m = re.search(r"TEMP_VERIFY_PANEL_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_calls_verify_temp_patch():
    src = PANEL.read_text(encoding="utf-8")
    assert '"verify_temp_patch"' in src


def test_renders_failure_and_pass_states():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="temp-verify-failed-note"' in src
    assert 'data-testid="temp-verify-passed-note"' in src


def test_renders_diff_summary():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="temp-verify-diff-summary"' in src


def test_human_approval_required_always_visible():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="temp-verify-human-approval-required-note"' in src
    assert "Human approval is required" in src


def test_source_unchanged_note():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="temp-verify-source-unchanged-note"' in src
    assert "not modified" in src.lower()


def test_no_source_apply_control():
    src = PANEL.read_text(encoding="utf-8")
    for n in ("Apply to Source", "Commit to Source", "applyToSource"):
        assert n not in src


def test_lock_manifest_exists():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_TEMP_VERIFY_PANEL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_TEMP_VERIFY_PANEL_LOCK_001" in ids
