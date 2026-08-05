"""Tests for DETERMINEX_REACT_USER_LEVEL_TEACHING_MODE_LOCK_001."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PANEL_PATH = (
    _REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "ide-product-shell"
    / "UserLevelTeachingMode.tsx"
)
LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_REACT_USER_LEVEL_TEACHING_MODE_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_react_user_level_teaching_mode"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


REQUIRED_LEVELS = (
    "beginner_no_experience",
    "learner",
    "vibe_coder",
    "junior_developer",
    "professional_developer",
    "maintainer",
    "security_conscious_operator",
    "power_user",
)


def _src() -> str:
    return PANEL_PATH.read_text(encoding="utf-8")


def test_panel_file_exists():
    assert PANEL_PATH.is_file()


def test_status_tokens_declared():
    src = _src()
    for t in (
        "REACT_USER_LEVEL_TEACHING_MODE_PASSED",
        "REACT_USER_LEVEL_TEACHING_MODE_BLOCKED_PROOF_HIDDEN",
        "REACT_USER_LEVEL_TEACHING_MODE_BLOCKED_AUTHORITY_BYPASS",
        "REACT_USER_LEVEL_TEACHING_MODE_BLOCKED_MISSING_BLOCKED_REASON",
    ):
        assert t in src


def test_all_eight_levels_present():
    src = _src()
    for level in REQUIRED_LEVELS:
        assert f'"{level}"' in src, level


def test_panel_renders_option_per_level():
    src = _src()
    for level in REQUIRED_LEVELS:
        assert "user-level-option-${l}" in src or f"user-level-option-{level}" in src, level


def test_invariants_are_constants_not_per_level():
    """Hard invariants must be constants, not derived from the chosen
    level. The level controls explanation detail only."""
    src = _src()
    assert "const proofStatusVisible = true;" in src
    assert "const authorityGatesActive = true;" in src
    assert "const teachingWindowExplainsBlockedReason = true;" in src
    assert "const trainingStaysFalse = true;" in src


def test_invariant_display_visible():
    src = _src()
    for tid in (
        "user-level-proof-status-visible-flag",
        "user-level-authority-gates-active-flag",
        "user-level-teaching-window-flag",
        "user-level-training-stays-false-flag",
    ):
        assert f'data-testid="{tid}"' in src, tid


def test_captions_present():
    src = _src()
    assert 'data-testid="user-level-beginner-does-not-hide-proof"' in src
    assert "Beginner mode does NOT hide proof." in src
    assert 'data-testid="user-level-professional-does-not-bypass-proof"' in src
    assert "Professional / power mode does NOT bypass proof." in src
    assert 'data-testid="user-level-changes-detail-only"' in src
    assert "User level changes EXPLANATION DETAIL only" in src


def test_no_per_level_authority_override():
    src = _src()
    # Forbidden patterns that would tie authority to level.
    forbidden = (
        "if (level ===",
        "level === 'power_user' &&",
        "loosenGates",
        "disableGate",
        "bypassProof",
    )
    for f in forbidden:
        assert f not in src, f


def test_no_mutating_command_invoked():
    src = _src()
    assert "invokeUnifiedProductCommand(" in src
    assert '"get_user_level_teaching_windows"' in src
    for forbidden in ("apply_source", "approve_packet", "write_training", "release_workflow"):
        assert forbidden not in src


def test_ready_does_not_mean_authorized_present():
    src = _src()
    assert "READY_DOES_NOT_MEAN_AUTHORIZED" in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_REACT_USER_LEVEL_TEACHING_MODE_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    assert sorted(EVIDENCE_DIR.glob("run_*.json"))


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_REACT_USER_LEVEL_TEACHING_MODE_LOCK_001" in ids
