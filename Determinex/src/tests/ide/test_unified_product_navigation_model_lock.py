"""Tests for DETERMINEX_UNIFIED_PRODUCT_NAVIGATION_MODEL_LOCK_001."""

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

nav = importlib.import_module("ide.unified_product_navigation_model")
nav_rec = importlib.import_module("ide.unified_product_navigation_model_record")

LOCK_PATH = (
    _REPO_ROOT
    / "locks"
    / "sentinel"
    / ("DETERMINEX_UNIFIED_PRODUCT_NAVIGATION_MODEL_LOCK_001.json")
)
EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / ("determinex_unified_product_navigation_model")
)
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Surface inventory
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(nav_rec.UNIFIED_PRODUCT_NAVIGATION_MODEL_STATUS_TOKENS) == {
        "UNIFIED_PRODUCT_NAVIGATION_MODEL_WRITTEN",
        "UNIFIED_PRODUCT_NAVIGATION_MODEL_VALIDATED",
        "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION",
        "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_MISSING_SURFACE",
    }


def test_five_required_surfaces():
    assert nav.UNIFIED_PRODUCT_SURFACES == (
        "idea_lab",
        "repo_clinic",
        "maintenance_bay",
        "learning_studio",
        "proof_operator_center",
    )


def test_canonical_surfaces_match_required_set():
    keys = {s.key for s in nav.canonical_surfaces()}
    assert keys == set(nav.UNIFIED_PRODUCT_SURFACES)


# ---------------------------------------------------------------------------
# Per-surface declarations
# ---------------------------------------------------------------------------
def test_every_surface_has_purpose_and_title():
    for s in nav.canonical_surfaces():
        assert s.title.strip(), s.key
        assert s.purpose.strip(), s.key


def test_every_surface_has_target_users():
    for s in nav.canonical_surfaces():
        assert len(s.target_users) >= 1, s.key


def test_every_surface_has_beginner_and_professional_view():
    for s in nav.canonical_surfaces():
        assert s.beginner_view.strip(), s.key
        assert s.professional_view.strip(), s.key


def test_every_surface_has_inputs_and_outputs():
    for s in nav.canonical_surfaces():
        assert len(s.inputs) >= 1, s.key
        assert len(s.outputs) >= 1, s.key


def test_every_surface_has_status_states():
    for s in nav.canonical_surfaces():
        assert len(s.status_states) >= 1, s.key


def test_every_surface_has_blocked_states():
    """Hard rule: every area must have visible blocked/unsupported states."""
    for s in nav.canonical_surfaces():
        assert len(s.blocked_states) >= 1, s.key


def test_every_surface_has_proof_requirements():
    for s in nav.canonical_surfaces():
        assert len(s.proof_evidence_requirements) >= 1, s.key


def test_every_surface_has_claim_caveats():
    for s in nav.canonical_surfaces():
        assert len(s.claim_caveats) >= 1, s.key


# ---------------------------------------------------------------------------
# Shared authority vocabulary
# ---------------------------------------------------------------------------
def test_shared_authority_vocabulary_eight_classes():
    assert nav.SHARED_AUTHORITY_VOCABULARY == (
        "capability_available",
        "evidence_present",
        "request_pending",
        "admission_present",
        "approval_present",
        "execution_authorized",
        "source_mutation_authorized",
        "training_eligible",
    )


# ---------------------------------------------------------------------------
# Hard rules on per-surface boundaries
# ---------------------------------------------------------------------------
def test_learning_studio_boundary_is_non_mutating():
    ls = next(s for s in nav.canonical_surfaces() if s.key == "learning_studio")
    bound = ls.source_mutation_boundary.lower()
    assert "non-mutating" in bound or "routes to" in bound, bound


def test_proof_operator_center_boundary_is_read_only():
    pc = next(s for s in nav.canonical_surfaces() if s.key == "proof_operator_center")
    bound = pc.source_mutation_boundary.lower()
    assert "read-only" in bound or "non-authorizing" in bound, bound


def test_no_surface_opens_training():
    for s in nav.canonical_surfaces():
        bound = s.training_eligibility_boundary.lower()
        assert "training enabled" not in bound
        assert "opens training" not in bound
        assert "training eligible by default" not in bound
        # Must say one of False / does not open.
        assert "false" in bound or "does not open" in bound, s.key


def test_no_surface_implies_authorization_from_readiness():
    """No status state in any surface may use the literal token
    SOURCE_MUTATION_AUTHORIZED unless the surface explicitly belongs
    to a flow that ends in apply (repo_clinic, maintenance_bay are
    the only two with that token in their status_states)."""
    for s in nav.canonical_surfaces():
        for st in s.status_states:
            if st == "SOURCE_MUTATION_AUTHORIZED":
                assert s.key in ("repo_clinic", "maintenance_bay"), (
                    f"{s.key} declares SOURCE_MUTATION_AUTHORIZED outside "
                    "the two repair-side surfaces"
                )


# ---------------------------------------------------------------------------
# build_record happy / synthetic violations
# ---------------------------------------------------------------------------
def test_build_record_is_validated():
    rec = nav.build_record()
    assert rec.is_written, rec.notes
    assert rec.decision == "UNIFIED_PRODUCT_NAVIGATION_MODEL_VALIDATED"
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_build_record_serializes():
    rec = nav.build_record()
    blob = json.loads(rec.to_json())
    assert len(blob["surfaces"]) == 5
    keys = {s["key"] for s in blob["surfaces"]}
    assert keys == set(nav.UNIFIED_PRODUCT_SURFACES)


def test_synthetic_missing_surface_blocks(monkeypatch):
    bad = tuple(s for s in nav._CANONICAL_SURFACES if s.key != "maintenance_bay")
    monkeypatch.setattr(nav, "_CANONICAL_SURFACES", bad)
    rec = nav.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_MISSING_SURFACE"


def test_synthetic_blocked_states_empty_blocks(monkeypatch):
    bad = list(nav._CANONICAL_SURFACES)
    for i, s in enumerate(bad):
        if s.key == "idea_lab":
            bad[i] = dataclasses.replace(s, blocked_states=())
    monkeypatch.setattr(nav, "_CANONICAL_SURFACES", tuple(bad))
    rec = nav.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION"


def test_synthetic_open_by_default_phrase_blocks(monkeypatch):
    bad = list(nav._CANONICAL_SURFACES)
    for i, s in enumerate(bad):
        if s.key == "idea_lab":
            bad[i] = dataclasses.replace(
                s,
                source_mutation_boundary="open by default for fixtures",
            )
    monkeypatch.setattr(nav, "_CANONICAL_SURFACES", tuple(bad))
    rec = nav.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION"


def test_synthetic_training_enabled_blocks(monkeypatch):
    bad = list(nav._CANONICAL_SURFACES)
    for i, s in enumerate(bad):
        if s.key == "idea_lab":
            bad[i] = dataclasses.replace(
                s,
                training_eligibility_boundary="training enabled in beginner mode",
            )
    monkeypatch.setattr(nav, "_CANONICAL_SURFACES", tuple(bad))
    rec = nav.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION"


def test_synthetic_learning_studio_could_mutate_blocks(monkeypatch):
    bad = list(nav._CANONICAL_SURFACES)
    for i, s in enumerate(bad):
        if s.key == "learning_studio":
            bad[i] = dataclasses.replace(
                s,
                source_mutation_boundary="may apply teaching examples directly",
            )
    monkeypatch.setattr(nav, "_CANONICAL_SURFACES", tuple(bad))
    rec = nav.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION"


def test_synthetic_proof_center_writable_blocks(monkeypatch):
    bad = list(nav._CANONICAL_SURFACES)
    for i, s in enumerate(bad):
        if s.key == "proof_operator_center":
            bad[i] = dataclasses.replace(
                s,
                source_mutation_boundary="may write training rows from queue",
            )
    monkeypatch.setattr(nav, "_CANONICAL_SURFACES", tuple(bad))
    rec = nav.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_UNIFIED_PRODUCT_NAVIGATION_MODEL_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_UNIFIED_PRODUCT_NAVIGATION_MODEL_LOCK_001" in ids
