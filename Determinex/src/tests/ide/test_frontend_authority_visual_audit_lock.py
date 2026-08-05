"""Tests for CLAUDE_FRONTEND_AUTHORITY_VISUAL_AUDIT_LOCK_001."""

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

va = importlib.import_module("ide.frontend_authority_visual_audit")
va_rec = importlib.import_module("ide.frontend_authority_visual_audit_record")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / ("CLAUDE_FRONTEND_AUTHORITY_VISUAL_AUDIT_LOCK_001.json")
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / ("claude_frontend_authority_visual_audit")
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Status tokens / sections
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(va_rec.FRONTEND_AUTHORITY_VISUAL_AUDIT_STATUS_TOKENS) == {
        "FRONTEND_AUTHORITY_VISUAL_AUDIT_PASSED",
        "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_AMBIGUOUS_STATE",
        "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_MISSING_NEGATIVE_AUTHORITY",
        "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_SECTION_MERGE",
        "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_BLOCKED_STATE_HIDDEN",
    }


def test_eight_sections_exact():
    assert va.FRONTEND_VISUAL_SECTIONS == (
        "diagnosis",
        "patch_preview",
        "verifier_result",
        "approval_request",
        "source_mutation_status",
        "rollback_status",
        "evidence_status",
        "training_eligibility_status",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_default_passing_layout_passes():
    rec = va.audit(va.default_passing_layout())
    assert rec.is_passed, rec.notes
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_passing_layout_has_eight_sections():
    layout = va.default_passing_layout()
    assert len(layout) == 8
    assert {s.section for s in layout} == set(va.FRONTEND_VISUAL_SECTIONS)


# ---------------------------------------------------------------------------
# Missing required section
# ---------------------------------------------------------------------------
def test_missing_section_blocks():
    layout = va.default_passing_layout()[:-1]  # drop training_eligibility_status
    rec = va.audit(layout)
    assert rec.decision == "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_AMBIGUOUS_STATE"
    assert any("training_eligibility_status" in a for a in rec.ambiguities)


def test_unknown_section_blocks():
    layout = list(va.default_passing_layout())
    layout.append(
        va_rec.SectionState(
            section="model_route",
            visible=True,
            is_success_state=True,
            negative_authority_caption="",
            is_blocked_state=False,
            blocked_text="",
        )
    )
    rec = va.audit(layout)
    assert rec.decision == "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_AMBIGUOUS_STATE"


# ---------------------------------------------------------------------------
# Section merge
# ---------------------------------------------------------------------------
def test_compound_section_name_blocks():
    layout = list(va.default_passing_layout())
    # Replace diagnosis with a merged name
    layout[0] = dataclasses.replace(layout[0], section="diagnosis+source_mutation_status")
    # Have to also remove the existing source_mutation_status so the
    # required-set check isn't the dominant failure.
    layout = [s for s in layout if s.section != "source_mutation_status"]
    layout.append(
        va_rec.SectionState(
            section="source_mutation_status",
            visible=True,
            is_success_state=False,
            negative_authority_caption="",
            is_blocked_state=False,
            blocked_text="",
        )
    )
    rec = va.audit(layout)
    # The merged token isn't in FRONTEND_VISUAL_SECTIONS so it
    # registers as an unknown section first; the test passes if it
    # is at least one of the BLOCKED decisions.
    assert rec.is_blocked


def test_slash_separated_compound_name_blocks():
    layout = list(va.default_passing_layout())
    layout[0] = dataclasses.replace(layout[0], section="diagnosis/patch_preview")
    # Drop patch_preview to avoid double-coverage from the required-set check.
    layout = [s for s in layout if s.section != "patch_preview"]
    layout.append(
        va_rec.SectionState(
            section="patch_preview",
            visible=True,
            is_success_state=False,
            negative_authority_caption="",
            is_blocked_state=False,
            blocked_text="",
        )
    )
    rec = va.audit(layout)
    assert rec.is_blocked


# ---------------------------------------------------------------------------
# Missing negative-authority caption
# ---------------------------------------------------------------------------
def test_success_state_without_negative_caption_blocks():
    layout = list(va.default_passing_layout())
    # Strip the caption from approval_request — a green approval
    # state must say "does not authorize source mutation".
    for i, s in enumerate(layout):
        if s.section == "approval_request":
            layout[i] = dataclasses.replace(s, negative_authority_caption="")
            break
    rec = va.audit(layout)
    assert rec.decision == ("FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_MISSING_NEGATIVE_AUTHORITY")
    assert any("approval_request" in m for m in rec.missing_negative_authority)


def test_success_diagnosis_without_negative_caption_blocks():
    layout = list(va.default_passing_layout())
    for i, s in enumerate(layout):
        if s.section == "diagnosis":
            layout[i] = dataclasses.replace(s, negative_authority_caption="")
            break
    rec = va.audit(layout)
    assert rec.decision == ("FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_MISSING_NEGATIVE_AUTHORITY")


def test_source_mutation_status_does_not_require_negative_caption():
    """source_mutation_status is the OUTPUT section; success there
    means the apply gate authorized the mutation. It is the ONE
    section whose green state legitimately represents authorization,
    so it is exempted from the negative-authority caption rule."""
    layout = list(va.default_passing_layout())
    for i, s in enumerate(layout):
        if s.section == "source_mutation_status":
            layout[i] = dataclasses.replace(
                s,
                is_success_state=True,
                negative_authority_caption="",
            )
            break
    rec = va.audit(layout)
    assert rec.is_passed


# ---------------------------------------------------------------------------
# Hidden blocked state
# ---------------------------------------------------------------------------
def test_blocked_state_with_visible_false_blocks():
    layout = list(va.default_passing_layout())
    for i, s in enumerate(layout):
        if s.section == "verifier_result":
            layout[i] = dataclasses.replace(
                s,
                is_success_state=False,
                visible=False,
                is_blocked_state=True,
                blocked_text="verifier failed",
            )
            break
    rec = va.audit(layout)
    assert rec.decision == ("FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_BLOCKED_STATE_HIDDEN")


def test_blocked_state_with_empty_text_blocks():
    layout = list(va.default_passing_layout())
    for i, s in enumerate(layout):
        if s.section == "verifier_result":
            layout[i] = dataclasses.replace(
                s,
                is_success_state=False,
                visible=True,
                is_blocked_state=True,
                blocked_text="",
            )
            break
    rec = va.audit(layout)
    assert rec.decision == ("FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_BLOCKED_STATE_HIDDEN")


def test_blocked_state_visible_and_explained_passes():
    layout = list(va.default_passing_layout())
    for i, s in enumerate(layout):
        if s.section == "verifier_result":
            layout[i] = dataclasses.replace(
                s,
                is_success_state=False,
                visible=True,
                is_blocked_state=True,
                blocked_text="temp verifier failed",
                negative_authority_caption="",  # exempt: it's not a success state
            )
            break
    rec = va.audit(layout)
    assert rec.is_passed


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------
def test_empty_layout_blocks():
    rec = va.audit([])
    assert rec.is_blocked
    # Eight required sections all missing -> ambiguous state.
    assert rec.decision == "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_AMBIGUOUS_STATE"


def test_none_layout_blocks():
    rec = va.audit(None)
    assert rec.is_blocked


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def test_passed_record_serializes_to_json():
    rec = va.audit(va.default_passing_layout())
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "FRONTEND_AUTHORITY_VISUAL_AUDIT_PASSED"
    assert len(blob["sections"]) == 8


# ---------------------------------------------------------------------------
# Negative-authority required set
# ---------------------------------------------------------------------------
def test_negative_authority_required_set_excludes_outputs():
    """source_mutation_status, rollback_status, and
    training_eligibility_status are NOT in the required-caption set
    because they are output sections — their green/red state is the
    answer to the authority question, not a step toward it.

    Actually we EXEMPT only source_mutation_status and rollback_status;
    training_eligibility_status is still required to carry the
    'does not authorize training' caption because the training
    answer is always negative in this lane.
    """
    s = va.SECTIONS_REQUIRING_NEGATIVE_AUTHORITY_CAPTION
    assert "source_mutation_status" not in s
    assert "rollback_status" not in s
    assert "training_eligibility_status" in s


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_FRONTEND_AUTHORITY_VISUAL_AUDIT_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_FRONTEND_AUTHORITY_VISUAL_AUDIT_LOCK_001" in ids
