"""Tests for CLAUDE_PUBLIC_CLAIMS_LEDGER_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

pcl = importlib.import_module("repair.public_claims_ledger")
pcl_rec = importlib.import_module("repair.public_claims_ledger_record")

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / ("CLAUDE_PUBLIC_CLAIMS_LEDGER_LOCK_001.json")
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / ("claude_public_claims_ledger")
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


# ---------------------------------------------------------------------------
# Status tokens / classifications
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(pcl_rec.PUBLIC_CLAIMS_LEDGER_STATUS_TOKENS) == {
        "PUBLIC_CLAIMS_LEDGER_WRITTEN",
        "PUBLIC_CLAIMS_LEDGER_BLOCKED_OVERCLAIM",
        "PUBLIC_CLAIMS_LEDGER_BLOCKED_IMPLEMENTATION_AMBIGUITY",
    }


def test_five_classifications_exact():
    assert set(pcl_rec.PUBLIC_CLAIM_CLASSIFICATIONS) == {
        "implemented",
        "implemented_but_gated_or_blocked",
        "planned",
        "research_track",
        "not_claimed",
    }


# ---------------------------------------------------------------------------
# Canonical ledger
# ---------------------------------------------------------------------------
def test_required_keys_present_in_canonical_ledger():
    keys = {c.key for c in pcl.canonical_ledger()}
    missing = pcl.REQUIRED_CLAIM_KEYS - keys
    assert not missing, f"required keys missing: {missing!r}"


def test_canonical_ledger_classifications_all_valid():
    for c in pcl.canonical_ledger():
        assert c.classification in pcl_rec.PUBLIC_CLAIM_CLASSIFICATIONS, c.key


def test_canonical_ledger_short_all_nonempty():
    for c in pcl.canonical_ledger():
        assert c.short.strip(), c.key


# ---------------------------------------------------------------------------
# Live record
# ---------------------------------------------------------------------------
def test_build_record_is_written():
    rec = pcl.build_record()
    assert rec.is_written, (
        f"ledger blocked: overclaims={rec.overclaims!r}; "
        f"ambiguities={rec.implementation_ambiguities!r}"
    )
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False


def test_record_serializes_to_json():
    rec = pcl.build_record()
    blob = json.loads(rec.to_json())
    assert blob["decision"] == "PUBLIC_CLAIMS_LEDGER_WRITTEN"
    keys = {c["key"] for c in blob["claims"]}
    assert keys >= pcl.REQUIRED_CLAIM_KEYS


# ---------------------------------------------------------------------------
# Hard rules — claim-specific
# ---------------------------------------------------------------------------
def test_training_eligibility_not_implemented():
    for c in pcl.canonical_ledger():
        if c.key == "training_eligibility":
            assert c.classification != "implemented"
            assert c.classification != "implemented_but_gated_or_blocked"
            return
    raise AssertionError("training_eligibility missing")


def test_release_readiness_not_implemented():
    for c in pcl.canonical_ledger():
        if c.key == "release_readiness":
            assert c.classification not in pcl_rec.CLASSIFICATIONS_THAT_IMPLY_LIVE_CAPABILITY
            return
    raise AssertionError("release_readiness missing")


def test_public_packaging_not_implemented():
    for c in pcl.canonical_ledger():
        if c.key == "public_packaging":
            assert c.classification not in pcl_rec.CLASSIFICATIONS_THAT_IMPLY_LIVE_CAPABILITY
            return
    raise AssertionError("public_packaging missing")


def test_federated_forge_and_mobile_console_are_research_track():
    found = {
        c.key: c.classification
        for c in pcl.canonical_ledger()
        if c.key in ("federated_forge", "mobile_console")
    }
    assert found["federated_forge"] == "research_track"
    assert found["mobile_console"] == "research_track"


def test_no_claim_implies_benchmark_execution():
    """The Claude lane must not imply benchmark execution; rung 7's
    overclaim-rule scans keys for benchmark/programbench/swebench."""
    rec = pcl.build_record()
    # build_record's hard rule 3 would have raised if any claim
    # contained benchmark keywords.
    for c in pcl.canonical_ledger():
        kl = c.key.lower()
        assert "benchmark" not in kl
        assert "programbench" not in kl
        assert "swebench" not in kl
    assert rec.is_written


def test_source_mutation_claim_is_gated():
    for c in pcl.canonical_ledger():
        if c.key == "source_mutation":
            assert c.classification == "implemented_but_gated_or_blocked"
            assert c.blocks_or_gates
            assert "approval_required" in c.blocks_or_gates
            assert "symlink_refused" in c.blocks_or_gates
            return
    raise AssertionError("source_mutation missing")


# ---------------------------------------------------------------------------
# Synthetic violation injection — confirm hard rules fire
# ---------------------------------------------------------------------------
def test_synthetic_training_implemented_triggers_overclaim(monkeypatch):
    """If we forcibly reclassify training_eligibility as
    'implemented', build_record must return BLOCKED_OVERCLAIM."""
    bad = list(pcl._CANONICAL_LEDGER)
    for i, c in enumerate(bad):
        if c.key == "training_eligibility":
            bad[i] = pcl_rec.PublicClaim(
                key=c.key,
                classification="implemented",
                short=c.short,
                evidence_ref=c.evidence_ref,
                blocks_or_gates=c.blocks_or_gates,
            )
    monkeypatch.setattr(pcl, "_CANONICAL_LEDGER", tuple(bad))
    rec = pcl.build_record()
    assert rec.is_blocked
    assert rec.decision == "PUBLIC_CLAIMS_LEDGER_BLOCKED_OVERCLAIM"


def test_synthetic_release_implemented_triggers_overclaim(monkeypatch):
    bad = list(pcl._CANONICAL_LEDGER)
    for i, c in enumerate(bad):
        if c.key == "release_readiness":
            bad[i] = pcl_rec.PublicClaim(
                key=c.key,
                classification="implemented",
                short=c.short,
                evidence_ref=c.evidence_ref,
            )
    monkeypatch.setattr(pcl, "_CANONICAL_LEDGER", tuple(bad))
    rec = pcl.build_record()
    assert rec.decision == "PUBLIC_CLAIMS_LEDGER_BLOCKED_OVERCLAIM"


def test_synthetic_benchmark_key_triggers_overclaim(monkeypatch):
    bad = list(pcl._CANONICAL_LEDGER) + [
        pcl_rec.PublicClaim(
            key="programbench_execution",
            classification="implemented",
            short="x",
            evidence_ref="x",
        ),
    ]
    monkeypatch.setattr(pcl, "_CANONICAL_LEDGER", tuple(bad))
    # Also extend required set so missing-key check doesn't fire first.
    rec = pcl.build_record()
    assert rec.decision == "PUBLIC_CLAIMS_LEDGER_BLOCKED_OVERCLAIM"


def test_synthetic_missing_required_key_triggers_ambiguity(monkeypatch):
    bad = tuple(c for c in pcl._CANONICAL_LEDGER if c.key != "rollback_snapshot")
    monkeypatch.setattr(pcl, "_CANONICAL_LEDGER", bad)
    rec = pcl.build_record()
    assert rec.decision == "PUBLIC_CLAIMS_LEDGER_BLOCKED_IMPLEMENTATION_AMBIGUITY"


def test_synthetic_unknown_classification_triggers_ambiguity(monkeypatch):
    bad = list(pcl._CANONICAL_LEDGER)
    for i, c in enumerate(bad):
        if c.key == "post_apply_verifier":
            bad[i] = pcl_rec.PublicClaim(
                key=c.key,
                classification="ALMOST_IMPLEMENTED",
                short=c.short,
                evidence_ref=c.evidence_ref,
            )
    monkeypatch.setattr(pcl, "_CANONICAL_LEDGER", tuple(bad))
    rec = pcl.build_record()
    assert rec.decision == "PUBLIC_CLAIMS_LEDGER_BLOCKED_IMPLEMENTATION_AMBIGUITY"


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_PUBLIC_CLAIMS_LEDGER_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_PUBLIC_CLAIMS_LEDGER_LOCK_001" in ids
