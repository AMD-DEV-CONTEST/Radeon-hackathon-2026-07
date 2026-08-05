"""Tests for IDE_APPROVAL_UX_COPY_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

copy_mod = importlib.import_module("ide.approval_ux_copy")

APPROVAL_UX_COPY = copy_mod.APPROVAL_UX_COPY
REQUIRED_SECTIONS = copy_mod.REQUIRED_SECTIONS
forbidden_phrases = copy_mod.forbidden_phrases

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_APPROVAL_UX_COPY_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_approval_ux_copy"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def test_all_required_sections_have_copy():
    for s in REQUIRED_SECTIONS:
        assert s in APPROVAL_UX_COPY
        assert APPROVAL_UX_COPY[s].strip() != ""


def test_no_forbidden_phrases_in_any_copy():
    blob = " ".join(APPROVAL_UX_COPY.values()).lower()
    for phrase in forbidden_phrases():
        assert phrase.lower() not in blob, f"Forbidden phrase present: {phrase}"


def test_advisory_phrasing_present_for_diagnosis():
    assert "suggestion" in APPROVAL_UX_COPY["diagnosis_advisory"].lower()
    assert "verifier" in APPROVAL_UX_COPY["diagnosis_advisory"].lower()


def test_patch_plan_marked_untrusted_or_draft():
    s = APPROVAL_UX_COPY["patch_plan_untrusted"].lower()
    assert "draft" in s or "untrusted" in s or "not been verified" in s


def test_temp_workspace_explanation_says_files_not_modified():
    assert "not modified" in APPROVAL_UX_COPY["temp_workspace_explanation"].lower()


def test_training_eligibility_notice_says_not_training_data():
    assert "training data" in APPROVAL_UX_COPY["training_eligibility_notice"].lower()


def test_no_blind_approval_section_present():
    s = APPROVAL_UX_COPY["no_blind_approval"].lower()
    assert "read the diff" in s
    assert "reject" in s


def test_lock_manifest_exists():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_APPROVAL_UX_COPY_LOCK_001"


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_APPROVAL_UX_COPY_LOCK_001" in ids
