"""Tests for FRONTEND_EVIDENCE_VIEWER_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
PANEL = _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair" / "EvidenceViewerPanel.tsx"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_EVIDENCE_VIEWER_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_evidence_viewer"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(
    {
        "EVIDENCE_VIEWER_READY",
        "EVIDENCE_VIEWER_READ_ONLY",
        "EVIDENCE_HEALTH_VISIBLE",
    }
)


def test_panel_exists():
    assert PANEL.is_file()


def test_status_tokens_exact():
    src = PANEL.read_text(encoding="utf-8")
    m = re.search(r"EVIDENCE_VIEWER_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_read_only_badge_visible():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="evidence-viewer-read-only-badge"' in src
    assert "Read-only" in src


def test_source_mutation_and_training_visible():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="evidence-viewer-source-mutation"' in src
    assert 'data-testid="evidence-viewer-training-eligible"' in src


def test_lock_ids_section_present():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="evidence-viewer-locks"' in src
    assert "Lock IDs" in src


def test_evidence_files_section_present():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="evidence-viewer-files"' in src


def test_evidence_health_note_present():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="evidence-viewer-health"' in src
    assert "determinex evidence validate" in src


def test_no_edit_controls():
    src = PANEL.read_text(encoding="utf-8")
    # No buttons that modify evidence.
    for n in ("delete", "edit", "<input", "Save evidence"):
        assert n.lower() not in src.lower() or n == "delete" and "deleted" in src.lower()
    # Specifically: no form / textarea / save / delete evidence
    assert "<textarea" not in src.lower()
    assert "<form" not in src.lower()


def test_lock_manifest_exists():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_EVIDENCE_VIEWER_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_EVIDENCE_VIEWER_LOCK_001" in ids
