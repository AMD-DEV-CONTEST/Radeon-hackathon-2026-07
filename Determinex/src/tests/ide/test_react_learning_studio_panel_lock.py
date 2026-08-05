"""Tests for DETERMINEX_REACT_LEARNING_STUDIO_PANEL_LOCK_001."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PANEL_PATH = (
    _REPO_ROOT / "frontend" / "src" / "components" / "ide-product-shell" / "LearningStudioPanel.tsx"
)
LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_REACT_LEARNING_STUDIO_PANEL_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_react_learning_studio_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


REQUIRED_MODES = (
    "explain_this_repo",
    "explain_this_file",
    "explain_this_error",
    "explain_this_test_failure",
    "teach_me_the_concept",
    "compare_possible_fixes",
    "walk_me_through_the_patch",
    "show_beginner_vs_professional_version",
    "generate_learning_checklist",
)


def _src() -> str:
    return PANEL_PATH.read_text(encoding="utf-8")


def test_panel_file_exists():
    assert PANEL_PATH.is_file()


def test_status_tokens_declared():
    src = _src()
    for t in (
        "REACT_LEARNING_STUDIO_PANEL_PASSED",
        "REACT_LEARNING_STUDIO_PANEL_BLOCKED_MUTATION_CONFUSION",
        "REACT_LEARNING_STUDIO_PANEL_BLOCKED_FALSE_SUCCESS",
        "REACT_LEARNING_STUDIO_PANEL_BLOCKED_MISSING_TEACHING_LEVELS",
    ):
        assert t in src


def test_all_nine_modes_present():
    src = _src()
    for m in REQUIRED_MODES:
        assert f'"{m}"' in src, m


def test_panel_renders_tab_per_mode():
    src = _src()
    for m in REQUIRED_MODES:
        assert (
            "learning-studio-mode-${m}" in src
            or f"learning-studio-mode-{m}" in src
            or f'data-mode="{m}"' in src
        ), m


def test_non_authorizing_caption_visible():
    src = _src()
    assert 'data-testid="learning-studio-non-authorizing-caption"' in src
    assert "Learning explains" in src
    assert "does NOT" in src


def test_routes_to_repo_clinic_present():
    src = _src()
    assert 'data-testid="learning-studio-route-to-repo-clinic"' in src
    assert 'data-routes-to="repo_clinic"' in src
    assert "Open in Repo Clinic" in src


def test_routes_to_idea_lab_present():
    src = _src()
    assert 'data-testid="learning-studio-route-to-idea-lab"' in src
    assert 'data-routes-to="idea_lab"' in src
    assert "Open in Idea Lab" in src


def test_teaching_window_explains_blocked_reason():
    src = _src()
    assert 'data-testid="learning-studio-teaching-window-blocked-reason"' in src
    assert "blocked" in src.lower()
    assert "gate" in src.lower()


def test_learning_cannot_authorize_captions():
    src = _src()
    assert 'data-testid="learning-studio-cannot-approve"' in src
    assert "Learning cannot approve a patch." in src
    assert 'data-testid="learning-studio-cannot-mark-repair-success"' in src
    assert "Learning cannot mark repair success." in src
    assert 'data-testid="learning-studio-cannot-mutate-source"' in src
    assert "Learning cannot mutate source." in src


def test_no_forbidden_success_text():
    src = _src().lower()
    for f in ("patch applied", "now fixed", "source mutation authorized", "training row written"):
        assert f not in src, f


def test_no_mutating_command_invoked():
    src = _src()
    assert "invokeUnifiedProductCommand(" in src
    assert '"get_learning_studio_workflow_state"' in src
    for forbidden in ("apply_source", "approve_packet", "write_training", "release_workflow"):
        assert forbidden not in src


def test_ready_does_not_mean_authorized_present():
    src = _src()
    assert "READY_DOES_NOT_MEAN_AUTHORIZED" in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_REACT_LEARNING_STUDIO_PANEL_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    assert sorted(EVIDENCE_DIR.glob("run_*.json"))


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_REACT_LEARNING_STUDIO_PANEL_LOCK_001" in ids
