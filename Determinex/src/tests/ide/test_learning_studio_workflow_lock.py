"""Tests for DETERMINEX_LEARNING_STUDIO_WORKFLOW_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ls = importlib.import_module("ide.learning_studio_workflow")
ls_rec = importlib.import_module("ide.learning_studio_workflow_record")

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_LEARNING_STUDIO_WORKFLOW_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_learning_studio_workflow"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _output(**overrides):
    base = dict(
        mode="explain_this_repo",
        text="this repo is a Python web app; main entrypoint is app.py",
        suggests_fix=False,
        suggests_new_project=False,
        routes_to="",
        claims_repair_success=False,
        claims_authorized_apply=False,
    )
    base.update(overrides)
    return ls_rec.LearningStudioOutput(**base)


# ---------------------------------------------------------------------------
# Tokens / modes
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(ls_rec.LEARNING_STUDIO_WORKFLOW_STATUS_TOKENS) == {
        "LEARNING_STUDIO_WORKFLOW_WRITTEN",
        "LEARNING_STUDIO_NON_AUTHORIZING_PASSED",
        "LEARNING_STUDIO_BLOCKED_MUTATION_CONFUSION",
        "LEARNING_STUDIO_BLOCKED_FALSE_SUCCESS",
    }


def test_modes_exact():
    assert ls.canonical_modes() == (
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


# ---------------------------------------------------------------------------
# Definition-only / happy paths
# ---------------------------------------------------------------------------
def test_no_output_returns_definition_record():
    rec = ls.evaluate(None)
    assert rec.is_written
    assert rec.output is None


def test_simple_explanation_passes():
    rec = ls.evaluate(_output())
    assert rec.is_written
    assert rec.decision == "LEARNING_STUDIO_NON_AUTHORIZING_PASSED"
    assert rec.non_authorizing is True


def test_compare_possible_fixes_without_routing_passes():
    """Comparing fixes does not equal suggesting one — no routing
    required if suggests_fix is False."""
    rec = ls.evaluate(
        _output(
            mode="compare_possible_fixes",
            text="option A uses asyncio; option B uses threads",
        )
    )
    assert rec.is_written


def test_walk_through_the_patch_passes():
    rec = ls.evaluate(
        _output(
            mode="walk_me_through_the_patch",
            text="step 1: read the diff; step 2: identify the changed function",
        )
    )
    assert rec.is_written


# ---------------------------------------------------------------------------
# False success refusals
# ---------------------------------------------------------------------------
def test_claims_repair_success_blocks():
    rec = ls.evaluate(_output(claims_repair_success=True))
    assert rec.decision == "LEARNING_STUDIO_BLOCKED_FALSE_SUCCESS"


def test_claims_authorized_apply_blocks():
    rec = ls.evaluate(_output(claims_authorized_apply=True))
    assert rec.decision == "LEARNING_STUDIO_BLOCKED_FALSE_SUCCESS"


def test_forbidden_phrase_now_fixed_blocks():
    rec = ls.evaluate(_output(text="The bug is now fixed in your repo."))
    assert rec.decision == "LEARNING_STUDIO_BLOCKED_FALSE_SUCCESS"


def test_forbidden_phrase_patch_applied_blocks():
    rec = ls.evaluate(_output(text="The patch applied successfully."))
    assert rec.decision == "LEARNING_STUDIO_BLOCKED_FALSE_SUCCESS"


def test_forbidden_phrase_training_row_written_blocks():
    rec = ls.evaluate(_output(text="A training row written for this case."))
    assert rec.decision == "LEARNING_STUDIO_BLOCKED_FALSE_SUCCESS"


# ---------------------------------------------------------------------------
# Mutation confusion refusals
# ---------------------------------------------------------------------------
def test_suggests_fix_without_routing_blocks():
    rec = ls.evaluate(_output(suggests_fix=True))
    assert rec.decision == "LEARNING_STUDIO_BLOCKED_MUTATION_CONFUSION"


def test_suggests_fix_routes_to_wrong_workflow_blocks():
    rec = ls.evaluate(_output(suggests_fix=True, routes_to="idea_lab"))
    assert rec.decision == "LEARNING_STUDIO_BLOCKED_MUTATION_CONFUSION"


def test_suggests_fix_routes_to_repo_clinic_passes():
    rec = ls.evaluate(
        _output(
            suggests_fix=True,
            routes_to="repo_clinic",
            text="Here's how you might fix it; press Open in Repo Clinic to proceed.",
        )
    )
    assert rec.is_written


def test_suggests_new_project_routes_to_idea_lab_passes():
    rec = ls.evaluate(
        _output(
            suggests_new_project=True,
            routes_to="idea_lab",
            text="This would be a new app; press Open in Idea Lab.",
        )
    )
    assert rec.is_written


def test_suggests_new_project_routes_to_repo_clinic_blocks():
    rec = ls.evaluate(
        _output(
            suggests_new_project=True,
            routes_to="repo_clinic",
        )
    )
    assert rec.decision == "LEARNING_STUDIO_BLOCKED_MUTATION_CONFUSION"


def test_unknown_mode_blocks():
    rec = ls.evaluate(_output(mode="explain_my_taxes"))
    assert rec.decision == "LEARNING_STUDIO_BLOCKED_MUTATION_CONFUSION"


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------
def test_passed_record_never_authorizes_mutation_or_training():
    rec = ls.evaluate(
        _output(
            suggests_fix=True,
            routes_to="repo_clinic",
            text="Use repo clinic to apply this.",
        )
    )
    assert rec.is_written
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_record_serializes():
    rec = ls.evaluate(_output())
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "LEARNING_STUDIO_NON_AUTHORIZING_PASSED"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_LEARNING_STUDIO_WORKFLOW_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_LEARNING_STUDIO_WORKFLOW_LOCK_001" in ids
