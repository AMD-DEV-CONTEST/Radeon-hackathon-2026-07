"""Tests for DETERMINEX_REACT_UNIFIED_NAVIGATION_PANEL_LOCK_001.

Static analysis of the TSX file: required sections, required strings,
forbidden authority-leak phrases, no source-mutation calls.
"""

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
    / "UnifiedNavigationPanel.tsx"
)
API_LIB_PATH = _REPO_ROOT / "frontend" / "src" / "lib" / "ide-product-shell-api.ts"
LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_REACT_UNIFIED_NAVIGATION_PANEL_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_react_unified_navigation_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _panel_src() -> str:
    return PANEL_PATH.read_text(encoding="utf-8")


def _api_src() -> str:
    return API_LIB_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Files exist
# ---------------------------------------------------------------------------
def test_panel_file_exists():
    assert PANEL_PATH.is_file()


def test_api_lib_exists():
    assert API_LIB_PATH.is_file()


# ---------------------------------------------------------------------------
# Status tokens declared
# ---------------------------------------------------------------------------
def test_required_status_tokens_declared_in_panel():
    src = _panel_src()
    for token in (
        "REACT_UNIFIED_NAVIGATION_PANEL_PASSED",
        "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_MISSING_SURFACE",
        "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_AUTHORITY_CONFUSION",
        "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_HIDDEN_BLOCKED_STATE",
    ):
        assert token in src, f"missing status token {token!r}"


# ---------------------------------------------------------------------------
# Five surfaces rendered
# ---------------------------------------------------------------------------
def test_panel_renders_tab_per_surface():
    src = _panel_src()
    for k in (
        "idea_lab",
        "repo_clinic",
        "maintenance_bay",
        "learning_studio",
        "proof_operator_center",
    ):
        assert "unified-navigation-tab-${k}" in src or f'"{k}"' in src, k


def test_surface_labels_declared():
    src = _panel_src()
    for label in (
        "Idea Lab",
        "Repo Clinic",
        "Maintenance Bay",
        "Learning Studio",
        "Proof / Operator Center",
    ):
        assert label in src, f"missing surface label {label!r}"


# ---------------------------------------------------------------------------
# Required per-surface sections
# ---------------------------------------------------------------------------
def test_panel_shows_purpose_per_surface():
    src = _panel_src()
    assert 'data-testid="unified-navigation-purpose"' in src


def test_panel_shows_blocked_states_per_surface():
    src = _panel_src()
    assert 'data-testid="unified-navigation-blocked-states"' in src
    # Must enumerate blocked states (the array is rendered).
    assert "activeSurface.blocked_states" in src


def test_panel_shows_what_is_allowed_per_surface():
    src = _panel_src()
    assert 'data-testid="unified-navigation-what-is-allowed"' in src


def test_panel_shows_what_is_not_authorized_per_surface():
    src = _panel_src()
    assert 'data-testid="unified-navigation-what-is-not-authorized"' in src
    # The text must include the boundary text.
    assert "source_mutation_boundary" in src
    assert "training_eligibility_boundary" in src


def test_panel_shows_ready_does_not_mean_authorized():
    src = _panel_src()
    assert "READY_DOES_NOT_MEAN_AUTHORIZED" in src
    # The constant value must contain the phrase.
    assert "Ready does NOT mean authorized" in _api_src()


def test_panel_shows_claim_caveats():
    src = _panel_src()
    assert 'data-testid="unified-navigation-claim-caveats"' in src


def test_panel_shows_shared_authority_vocabulary():
    src = _panel_src()
    assert "SHARED_AUTHORITY_VOCABULARY" in src
    assert 'data-testid="unified-navigation-authority-vocabulary"' in src


# ---------------------------------------------------------------------------
# Missing-surface visibility
# ---------------------------------------------------------------------------
def test_panel_surfaces_missing_surface_banner():
    src = _panel_src()
    assert 'data-testid="unified-navigation-missing-surface-banner"' in src
    assert "missingSurfaces" in src


# ---------------------------------------------------------------------------
# No green-without-negative-authority
# ---------------------------------------------------------------------------
def test_panel_has_no_unqualified_success_text():
    src = _panel_src()
    forbidden = (
        "All set!",
        "You're authorized",
        "Source mutation enabled",
        "Training enabled",
        "Ready means authorized",
    )
    for f in forbidden:
        assert f.lower() not in src.lower(), f"forbidden text {f!r}"


# ---------------------------------------------------------------------------
# No mutation / approval / training calls from frontend
# ---------------------------------------------------------------------------
def test_panel_does_not_call_mutating_command():
    src = _panel_src()
    forbidden_commands = (
        "apply_source",
        "write_training_row",
        "approve_packet",
        "grant_authorization",
        "release_workflow",
    )
    for cmd in forbidden_commands:
        assert cmd not in src, cmd


def test_panel_only_invokes_unified_product_navigation_model():
    src = _panel_src()
    # Should only invoke the read-only command.
    assert 'invokeUnifiedProductCommand("get_unified_product_navigation_model")' in src


def test_api_lib_refuses_authorized_or_training_eligible_response():
    src = _api_src()
    assert "frontend refused source_mutation_authorized=true" in src
    assert "frontend refused training_eligible=true" in src


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_REACT_UNIFIED_NAVIGATION_PANEL_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_REACT_UNIFIED_NAVIGATION_PANEL_LOCK_001" in ids
