"""Tests for CLAUDE_PROOF_BEFORE_MUTATION_DEMO_SCRIPT_LOCK_001."""

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

ds = importlib.import_module("repair.proof_before_mutation_demo_script")
ds_rec = importlib.import_module("repair.proof_before_mutation_demo_script_record")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / ("CLAUDE_PROOF_BEFORE_MUTATION_DEMO_SCRIPT_LOCK_001.json")
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / ("claude_proof_before_mutation_demo_script")
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Status tokens
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(ds_rec.PROOF_BEFORE_MUTATION_DEMO_STATUS_TOKENS) == {
        "PROOF_BEFORE_MUTATION_DEMO_SCRIPT_WRITTEN",
        "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_PATH_INCLUDED",
        "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_NETWORK_REQUIRED",
        "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_AUTHORITY_AMBIGUITY",
        "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_MISSING_BLOCKED_PATH",
        "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_MISSING_PHRASE",
    }


# ---------------------------------------------------------------------------
# Canonical paths
# ---------------------------------------------------------------------------
def test_happy_path_has_11_steps():
    happy = ds.canonical_happy_path()
    assert len(happy) == 11
    assert [s.n for s in happy] == list(range(1, 12))


def test_blocked_path_has_3_steps():
    blocked = ds.canonical_blocked_path()
    assert len(blocked) == 3
    assert [s.n for s in blocked] == [1, 2, 3]
    assert all(s.is_blocked_step for s in blocked)


def test_happy_path_steps_not_marked_blocked():
    for s in ds.canonical_happy_path():
        assert s.is_blocked_step is False


# ---------------------------------------------------------------------------
# Required phrase / fixture path
# ---------------------------------------------------------------------------
def test_phrase_constant():
    assert ds.PROOF_BEFORE_MUTATION_PHRASE == "Proof Before Mutation"


def test_fixture_repo_path_is_under_tests_fixtures():
    assert "tests/fixtures" in ds.DEMO_FIXTURE_REPO_PATH


def test_phrase_appears_somewhere_in_demo():
    haystack = " ".join(
        s.title + " " + s.description
        for s in (ds.canonical_happy_path() + ds.canonical_blocked_path())
    )
    assert ds.PROOF_BEFORE_MUTATION_PHRASE.lower() in haystack.lower()


# ---------------------------------------------------------------------------
# Build record
# ---------------------------------------------------------------------------
def test_build_record_is_written():
    rec = ds.build_record()
    assert rec.is_written, rec.notes
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_record_serializes_to_json():
    rec = ds.build_record()
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "PROOF_BEFORE_MUTATION_DEMO_SCRIPT_WRITTEN"
    assert len(blob["happy_path_steps"]) == 11
    assert len(blob["blocked_path_steps"]) == 3


def test_record_marks_no_network_no_docker_no_pb_no_training():
    rec = ds.build_record()
    assert rec.network_required is False
    assert rec.docker_required is False
    assert rec.programbench_required is False
    assert rec.training_rows_written is False


# ---------------------------------------------------------------------------
# Required content in happy path
# ---------------------------------------------------------------------------
def test_happy_path_step_titles_include_key_concepts():
    titles = " ".join(s.title.lower() for s in ds.canonical_happy_path())
    for kw in (
        "fixture",
        "detect issue",
        "diagnose",
        "quarantine",
        "temp verifier",
        "user approval",
        "body hash",
        "source mutation",
        "post-apply verifier",
        "evidence",
        "training",
    ):
        assert kw in titles, f"happy-path titles missing concept: {kw!r}"


def test_blocked_path_covers_three_scenarios():
    titles = [s.title.lower() for s in ds.canonical_blocked_path()]
    # Missing approval, changed body, missing verifier — the three
    # scenarios required by the campaign spec.
    text = " ".join(titles)
    assert "missing approval" in text
    assert "changed patch body" in text
    assert "missing verifier" in text


# ---------------------------------------------------------------------------
# Synthetic violation tests — assert hard rules fire
# ---------------------------------------------------------------------------
def test_synthetic_network_call_triggers_block(monkeypatch):
    bad = list(ds.canonical_happy_path())
    bad[2] = dataclasses.replace(
        bad[2],
        description="call openai for diagnosis instead of local model",
    )
    monkeypatch.setattr(ds, "_HAPPY_PATH", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_NETWORK_REQUIRED"


def test_synthetic_docker_call_triggers_block(monkeypatch):
    bad = list(ds.canonical_happy_path())
    bad[4] = dataclasses.replace(
        bad[4],
        description="docker run determinex-verifier on temp workspace",
    )
    monkeypatch.setattr(ds, "_HAPPY_PATH", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_NETWORK_REQUIRED"


def test_synthetic_programbench_call_triggers_block(monkeypatch):
    bad = list(ds.canonical_happy_path())
    bad[1] = dataclasses.replace(
        bad[1],
        description="programbench eval against the fixture",
    )
    monkeypatch.setattr(ds, "_HAPPY_PATH", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_NETWORK_REQUIRED"


def test_synthetic_training_write_triggers_block(monkeypatch):
    bad = list(ds.canonical_happy_path())
    bad[10] = dataclasses.replace(
        bad[10],
        description="write training row to corpus on success",
    )
    monkeypatch.setattr(ds, "_HAPPY_PATH", tuple(bad))
    rec = ds.build_record()
    assert rec.is_blocked


def test_synthetic_real_user_repo_triggers_block(monkeypatch):
    bad = list(ds.canonical_happy_path())
    bad[0] = dataclasses.replace(
        bad[0],
        description="open real user repo and mutate live source",
    )
    monkeypatch.setattr(ds, "_HAPPY_PATH", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_PATH_INCLUDED"


def test_synthetic_blocked_step_not_marked(monkeypatch):
    bad = list(ds.canonical_blocked_path())
    bad[0] = dataclasses.replace(bad[0], is_blocked_step=False)
    monkeypatch.setattr(ds, "_BLOCKED_PATH", tuple(bad))
    rec = ds.build_record()
    assert rec.decision == "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_MISSING_BLOCKED_PATH"


def test_synthetic_missing_phrase_triggers_block(monkeypatch):
    bad_h = tuple(
        dataclasses.replace(s, title="X", description="Y") for s in ds.canonical_happy_path()
    )
    bad_b = tuple(
        dataclasses.replace(s, title="X", description="Y") for s in ds.canonical_blocked_path()
    )
    monkeypatch.setattr(ds, "_HAPPY_PATH", bad_h)
    monkeypatch.setattr(ds, "_BLOCKED_PATH", bad_b)
    rec = ds.build_record()
    assert rec.decision == "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_MISSING_PHRASE"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_PROOF_BEFORE_MUTATION_DEMO_SCRIPT_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_PROOF_BEFORE_MUTATION_DEMO_SCRIPT_LOCK_001" in ids
