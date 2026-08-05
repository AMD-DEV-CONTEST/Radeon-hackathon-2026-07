"""Tests for DETERMINEX_UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_LOCK_001."""

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

ds = importlib.import_module("repair.unified_product_splash_demo_spec")
ds_rec = importlib.import_module("repair.unified_product_splash_demo_spec_record")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_unified_product_splash_demo_spec"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Tokens / shape
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(ds_rec.UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_STATUS_TOKENS) == {
        "UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_WRITTEN",
        "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY",
        "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_AUTHORITY_CONFUSION",
        "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_MISSING_PROOF_VIEW",
    }


def test_sequence_five_steps_one_per_surface():
    seq = ds.canonical_sequence()
    assert len(seq) == 5
    assert [s.surface for s in seq] == [
        "idea_lab",
        "repo_clinic",
        "maintenance_bay",
        "learning_studio",
        "proof_operator_center",
    ]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_build_record_is_written():
    rec = ds.build_record()
    assert rec.is_written, rec.notes
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_required_tagline_present():
    seq = ds.canonical_sequence()
    haystack = " ".join(s.title + " " + s.description for s in seq).lower()
    assert ds.REQUIRED_TAGLINE.lower() in haystack


def test_required_phrases_present():
    seq = ds.canonical_sequence()
    haystack = " ".join(s.title + " " + s.description for s in seq).lower()
    for p in ds.REQUIRED_PHRASES:
        assert p.lower() in haystack, p


def test_required_negative_caveats_present():
    seq = ds.canonical_sequence()
    haystack = " ".join(s.title + " " + s.description for s in seq).lower()
    for c in ds.REQUIRED_NEGATIVE_CAVEATS:
        assert c.lower() in haystack, c


def test_record_marks_happy_blocked_teaching_proof():
    rec = ds.build_record()
    assert rec.happy_path_step_present
    assert rec.blocked_path_step_present
    assert rec.teaching_step_present
    assert rec.proof_view_step_present


def test_record_marks_no_infra_required():
    rec = ds.build_record()
    assert rec.network_required is False
    assert rec.docker_required is False
    assert rec.programbench_required is False
    assert rec.real_external_mutation is False


def test_record_serializes():
    rec = ds.build_record()
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_WRITTEN"
    assert len(blob["sequence"]) == 5


# ---------------------------------------------------------------------------
# Synthetic violations
# ---------------------------------------------------------------------------
def test_synthetic_drop_blocked_step_blocks(monkeypatch):
    bad = list(ds._CANONICAL_SEQUENCE)
    for i, s in enumerate(bad):
        if s.is_blocked_step:
            bad[i] = dataclasses.replace(s, is_blocked_step=False)
    monkeypatch.setattr(ds, "_CANONICAL_SEQUENCE", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_AUTHORITY_CONFUSION"


def test_synthetic_drop_teaching_step_blocks(monkeypatch):
    bad = list(ds._CANONICAL_SEQUENCE)
    for i, s in enumerate(bad):
        if s.is_teaching_step:
            bad[i] = dataclasses.replace(s, is_teaching_step=False)
    monkeypatch.setattr(ds, "_CANONICAL_SEQUENCE", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_AUTHORITY_CONFUSION"


def test_synthetic_drop_proof_step_blocks(monkeypatch):
    bad = list(ds._CANONICAL_SEQUENCE)
    for i, s in enumerate(bad):
        if s.is_proof_view:
            bad[i] = dataclasses.replace(s, is_proof_view=False)
    monkeypatch.setattr(ds, "_CANONICAL_SEQUENCE", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_MISSING_PROOF_VIEW"


def test_synthetic_network_call_blocks(monkeypatch):
    bad = list(ds._CANONICAL_SEQUENCE)
    bad[0] = dataclasses.replace(bad[0], description=bad[0].description + " call openai for plan")
    monkeypatch.setattr(ds, "_CANONICAL_SEQUENCE", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY"


def test_synthetic_docker_run_blocks(monkeypatch):
    bad = list(ds._CANONICAL_SEQUENCE)
    bad[1] = dataclasses.replace(bad[1], description=bad[1].description + " docker run determinex")
    monkeypatch.setattr(ds, "_CANONICAL_SEQUENCE", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY"


def test_synthetic_programbench_run_blocks(monkeypatch):
    bad = list(ds._CANONICAL_SEQUENCE)
    bad[2] = dataclasses.replace(
        bad[2], description=bad[2].description + " programbench eval the tool"
    )
    monkeypatch.setattr(ds, "_CANONICAL_SEQUENCE", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY"


def test_synthetic_real_user_repo_blocks(monkeypatch):
    bad = list(ds._CANONICAL_SEQUENCE)
    bad[1] = dataclasses.replace(
        bad[1], description=bad[1].description + " mutate the user's real repo"
    )
    monkeypatch.setattr(ds, "_CANONICAL_SEQUENCE", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY"


def test_synthetic_remove_tagline_blocks(monkeypatch):
    bad = list(ds._CANONICAL_SEQUENCE)
    for i, s in enumerate(bad):
        new_desc = s.description.replace("Proof Before Mutation", "magic Determinex")
        new_title = s.title.replace("Proof Before Mutation", "magic Determinex")
        bad[i] = dataclasses.replace(s, title=new_title, description=new_desc)
    monkeypatch.setattr(ds, "_CANONICAL_SEQUENCE", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY"


def test_synthetic_remove_negative_caveat_blocks(monkeypatch):
    """Drop 'not all apps' from the proof view step."""
    bad = list(ds._CANONICAL_SEQUENCE)
    for i, s in enumerate(bad):
        if s.is_proof_view:
            new_desc = s.description.replace("not all apps", "all apps")
            bad[i] = dataclasses.replace(s, description=new_desc)
    monkeypatch.setattr(ds, "_CANONICAL_SEQUENCE", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_LOCK_001" in ids
