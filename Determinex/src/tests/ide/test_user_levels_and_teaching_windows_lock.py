"""Tests for DETERMINEX_UNIFIED_USER_LEVELS_AND_TEACHING_WINDOWS_LOCK_001."""

from __future__ import annotations

import dataclasses
import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ul = importlib.import_module("ide.user_levels_and_teaching_windows")
ul_rec = importlib.import_module("ide.user_levels_and_teaching_windows_record")

LOCK_PATH = (
    _REPO_ROOT
    / "locks"
    / "sentinel"
    / "DETERMINEX_UNIFIED_USER_LEVELS_AND_TEACHING_WINDOWS_LOCK_001.json"
)
EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "determinex_unified_user_levels_and_teaching_windows"
)
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Tokens / inventory
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(ul_rec.USER_LEVELS_TEACHING_WINDOWS_STATUS_TOKENS) == {
        "USER_LEVELS_TEACHING_WINDOWS_WRITTEN",
        "USER_LEVELS_TEACHING_WINDOWS_VALIDATED",
        "USER_LEVELS_BLOCKED_PROOF_HIDDEN",
        "USER_LEVELS_BLOCKED_AUTHORITY_BYPASS",
    }


def test_eight_levels_exact():
    assert ul.USER_LEVELS == (
        "beginner_no_experience",
        "learner",
        "vibe_coder",
        "junior_developer",
        "professional_developer",
        "maintainer",
        "security_conscious_operator",
        "power_user",
    )


# ---------------------------------------------------------------------------
# Per-level declarations
# ---------------------------------------------------------------------------
def test_every_level_has_profile():
    profiles = ul.canonical_profiles()
    seen = {p.level for p in profiles}
    assert seen == set(ul.USER_LEVELS)


def test_every_level_has_default_explanations_and_detail():
    for p in ul.canonical_profiles():
        assert p.default_explanations.strip(), p.level
        assert p.level_of_detail.strip(), p.level
        assert p.ui_complexity in ("minimal", "moderate", "full"), p.level


def test_every_level_has_suggested_next_action():
    for p in ul.canonical_profiles():
        assert p.suggested_next_action.strip(), p.level


def test_every_level_has_teaching_windows():
    for p in ul.canonical_profiles():
        assert len(p.teaching_windows) >= 1, p.level


# ---------------------------------------------------------------------------
# Hard rules
# ---------------------------------------------------------------------------
def test_every_level_keeps_proof_visible():
    for p in ul.canonical_profiles():
        assert p.proof_status_visible is True, p.level


def test_every_level_keeps_authority_gates_active():
    for p in ul.canonical_profiles():
        assert p.authority_gates_active is True, p.level


def test_every_level_teaching_window_explains_blocked():
    for p in ul.canonical_profiles():
        assert p.teaching_window_explains_blocked_reason is True, p.level


def test_every_level_what_not_to_hide_mentions_training_stays_false():
    for p in ul.canonical_profiles():
        joined = " ".join(p.what_not_to_hide).lower()
        assert "training" in joined and "false" in joined, p.level


# ---------------------------------------------------------------------------
# build_record happy / synthetic violations
# ---------------------------------------------------------------------------
def test_build_record_is_validated():
    rec = ul.build_record()
    assert rec.is_written, rec.notes
    assert rec.decision == "USER_LEVELS_TEACHING_WINDOWS_VALIDATED"
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_record_serializes():
    rec = ul.build_record()
    blob = json.loads(rec.to_json())
    assert len(blob["levels"]) == 8


def test_synthetic_missing_level_blocks(monkeypatch):
    bad = tuple(p for p in ul._CANONICAL_PROFILES if p.level != "vibe_coder")
    monkeypatch.setattr(ul, "_CANONICAL_PROFILES", bad)
    rec = ul.build_record()
    assert rec.decision == "USER_LEVELS_BLOCKED_PROOF_HIDDEN"


def test_synthetic_beginner_hides_proof_blocks(monkeypatch):
    bad = list(ul._CANONICAL_PROFILES)
    for i, p in enumerate(bad):
        if p.level == "beginner_no_experience":
            bad[i] = dataclasses.replace(p, proof_status_visible=False)
    monkeypatch.setattr(ul, "_CANONICAL_PROFILES", tuple(bad))
    rec = ul.build_record()
    assert rec.decision == "USER_LEVELS_BLOCKED_PROOF_HIDDEN"


def test_synthetic_power_user_bypasses_gates_blocks(monkeypatch):
    bad = list(ul._CANONICAL_PROFILES)
    for i, p in enumerate(bad):
        if p.level == "power_user":
            bad[i] = dataclasses.replace(p, authority_gates_active=False)
    monkeypatch.setattr(ul, "_CANONICAL_PROFILES", tuple(bad))
    rec = ul.build_record()
    assert rec.decision == "USER_LEVELS_BLOCKED_AUTHORITY_BYPASS"


def test_synthetic_teaching_window_no_blocked_reason_blocks(monkeypatch):
    bad = list(ul._CANONICAL_PROFILES)
    for i, p in enumerate(bad):
        if p.level == "professional_developer":
            bad[i] = dataclasses.replace(p, teaching_window_explains_blocked_reason=False)
    monkeypatch.setattr(ul, "_CANONICAL_PROFILES", tuple(bad))
    rec = ul.build_record()
    assert rec.decision == "USER_LEVELS_BLOCKED_AUTHORITY_BYPASS"


def test_synthetic_what_not_to_hide_drops_training_blocks(monkeypatch):
    bad = list(ul._CANONICAL_PROFILES)
    for i, p in enumerate(bad):
        if p.level == "learner":
            bad[i] = dataclasses.replace(p, what_not_to_hide=("proof status",))
    monkeypatch.setattr(ul, "_CANONICAL_PROFILES", tuple(bad))
    rec = ul.build_record()
    assert rec.decision == "USER_LEVELS_BLOCKED_PROOF_HIDDEN"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_UNIFIED_USER_LEVELS_AND_TEACHING_WINDOWS_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_UNIFIED_USER_LEVELS_AND_TEACHING_WINDOWS_LOCK_001" in ids
