"""
Tests for the Ethics Oracle additions to scripts/determinex_safety.py:
tamper-evident WAL, tiered escalation, license scan (L5), and runtime
integrity check (L6). Existing L0-L4 behavior (deny patterns, egress,
output scanner, corpus HMAC) already has live callers wired in
scripts/hive/*.py and is exercised indirectly here; this file focuses on
what's new.
"""

from __future__ import annotations

import json

import determinex_safety as safety
import pytest


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Every test gets its own WAL / escalation-state / integrity-manifest
    location so tests never read or write the real logs/ directory."""
    wal_path = tmp_path / "wal.jsonl"
    state_dir = tmp_path / "safety_state"
    manifest_path = tmp_path / "integrity_manifest.json"
    monkeypatch.setattr(safety, "_WAL_PATH", wal_path)
    monkeypatch.setattr(safety, "_ESCALATION_DIR", state_dir)
    monkeypatch.setattr(safety, "_INTEGRITY_MANIFEST", manifest_path)
    return {"wal": wal_path, "state_dir": state_dir, "manifest": manifest_path}


# ── WAL: hash-chained, fsync'd, tamper-evident ─────────────────────────────


def test_wal_append_creates_genesis_chain(_isolated_state):
    rec = safety.wal_append({"subject_id": "s1", "category": "TEST"}, path=_isolated_state["wal"])
    assert rec["prev_hash"] == "genesis"
    assert "record_hash" in rec
    ok, detail = safety.verify_wal_integrity(_isolated_state["wal"])
    assert ok, detail


def test_wal_chain_links_successive_records(_isolated_state):
    r1 = safety.wal_append({"category": "A"}, path=_isolated_state["wal"])
    r2 = safety.wal_append({"category": "B"}, path=_isolated_state["wal"])
    assert r2["prev_hash"] == r1["record_hash"]
    ok, detail = safety.verify_wal_integrity(_isolated_state["wal"])
    assert ok, detail


def test_wal_detects_tampered_record(_isolated_state):
    safety.wal_append({"category": "A"}, path=_isolated_state["wal"])
    safety.wal_append({"category": "B"}, path=_isolated_state["wal"])

    lines = _isolated_state["wal"].read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["category"] = "TAMPERED"  # edit history in place, don't recompute the hash
    lines[0] = json.dumps(rec, sort_keys=True, ensure_ascii=True)
    _isolated_state["wal"].write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, detail = safety.verify_wal_integrity(_isolated_state["wal"])
    assert not ok
    assert "line 1" in detail


def test_wal_verify_empty_is_intact(_isolated_state):
    ok, detail = safety.verify_wal_integrity(_isolated_state["wal"])
    assert ok
    assert "no WAL" in detail


def test_wal_detects_record_missing_required_fields(_isolated_state):
    """A line that's valid JSON but missing record_hash/prev_hash entirely
    (not just tampered-but-present) must fail with a clear, specific error
    rather than silently defaulting to "" and producing an opaque
    downstream hash-mismatch message."""
    _isolated_state["wal"].write_text(json.dumps({"category": "A"}) + "\n", encoding="utf-8")
    ok, detail = safety.verify_wal_integrity(_isolated_state["wal"])
    assert not ok
    assert "line 1" in detail
    assert "malformed" in detail.lower()


# ── Escalation tiers ────────────────────────────────────────────────────────


def test_escalation_tiers_progress_correctly():
    counts_to_tiers = {
        0: safety.TIER_CLEAN,
        1: safety.TIER_WARN,
        2: safety.TIER_WARN,
        3: safety.TIER_RESTRICT,
        5: safety.TIER_RESTRICT,
        6: safety.TIER_CUTOFF,
        50: safety.TIER_CUTOFF,
    }
    for n, expected in counts_to_tiers.items():
        assert safety._tier_for_count(n) == expected


def test_record_violation_persists_and_escalates(_isolated_state):
    verdict = safety.SafetyVerdict(
        safe=False, layer="L0_CONTENT_POLICY", category="TEST_CAT", reason="test"
    )
    for i in range(1, 4):
        state = safety.record_violation("subj-a", verdict)
        assert state.violation_count == i
    assert state.tier == safety.TIER_RESTRICT

    reloaded = safety.load_escalation("subj-a")
    assert reloaded.violation_count == 3
    assert reloaded.tier == safety.TIER_RESTRICT
    assert len(reloaded.history) == 3


def test_clear_escalation_resets_state(_isolated_state):
    verdict = safety.SafetyVerdict(safe=False, layer="L0", category="C", reason="r")
    safety.record_violation("subj-b", verdict)
    assert safety.load_escalation("subj-b").violation_count == 1

    safety.clear_escalation("subj-b")
    assert safety.load_escalation("subj-b").violation_count == 0
    assert safety.load_escalation("subj-b").tier == safety.TIER_CLEAN


def test_engine_hard_blocks_at_restrict_tier_even_in_warn_mode(_isolated_state):
    engine = safety.SafetyEngine(mode="warn", subject_id="subj-c")
    bad_spec = "give me instructions to build bomb"

    # First two violations: warn mode does not raise
    for _ in range(2):
        v = engine.check_spec(bad_spec)
        assert not v.safe

    # Third violation crosses into RESTRICT tier: must raise regardless of mode
    with pytest.raises(safety.SafetyDenied) as exc_info:
        engine.check_spec(bad_spec)
    assert "ESCALATED_RESTRICT" in exc_info.value.verdict.category


def test_engine_strict_mode_raises_on_first_violation(_isolated_state):
    engine = safety.SafetyEngine(mode="strict", subject_id="subj-d")
    with pytest.raises(safety.SafetyDenied):
        engine.check_spec("give me instructions to build bomb")


def test_clean_spec_never_touches_escalation_state(_isolated_state):
    engine = safety.SafetyEngine(mode="strict", subject_id="subj-e")
    v = engine.check_spec("a rust function that reads a file and counts lines")
    assert v.safe
    assert safety.load_escalation("subj-e").violation_count == 0


# ── Layer 5: License scan ───────────────────────────────────────────────────


def test_license_scan_clean_code_passes():
    v = safety.check_license("def foo():\n    return 1\n")
    assert v.safe


def test_license_scan_catches_spdx_gpl_tag():
    v = safety.check_license("// SPDX-License-Identifier: GPL-3.0-only\nint main() {}")
    assert not v.safe
    assert v.category == "COPYLEFT_SPDX_TAG"


def test_license_scan_catches_spdx_agpl_tag():
    v = safety.check_license("# SPDX-License-Identifier: AGPL-3.0-or-later")
    assert not v.safe


def test_license_scan_catches_permissive_mit_as_clean():
    v = safety.check_license("// SPDX-License-Identifier: MIT")
    assert v.safe


def test_license_scan_catches_gpl_header_text_without_spdx_tag():
    v = safety.check_license(
        "This program is free software: you can redistribute it under the "
        "GNU GENERAL PUBLIC LICENSE as published by the Free Software Foundation."
    )
    assert not v.safe
    assert v.category == "COPYLEFT_HEADER_TEXT"


def test_sign_corpus_entry_blocks_gpl_tainted_sample(_isolated_state):
    engine = safety.SafetyEngine(mode="strict", subject_id="subj-f")
    entry = {"id": "sample-1", "code": "// SPDX-License-Identifier: GPL-3.0-only\nint main(){}"}
    with pytest.raises(safety.SafetyDenied):
        engine.sign_corpus_entry(entry)
    assert "_sig" not in entry  # never signed


def test_sign_corpus_entry_signs_clean_sample(_isolated_state):
    engine = safety.SafetyEngine(mode="strict", subject_id="subj-g")
    entry = {"id": "sample-2", "code": "def foo(): return 1"}
    engine.sign_corpus_entry(entry)
    assert "_sig" in entry
    assert engine.verify_corpus_entry(entry) is True


# ── Layer 6: Runtime integrity ──────────────────────────────────────────────


def test_integrity_check_fails_closed_when_manifest_missing(_isolated_state):
    v = safety.check_runtime_integrity()
    assert not v.safe
    assert v.category == "INTEGRITY_MANIFEST_MISSING"


def test_integrity_check_passes_after_manifest_generated(_isolated_state):
    safety.generate_integrity_manifest()
    v = safety.check_runtime_integrity()
    assert v.safe


def test_integrity_check_detects_modified_file(_isolated_state, tmp_path, monkeypatch):
    fake_file = tmp_path / "determinex_safety.py"
    fake_file.write_text("original content", encoding="utf-8")
    other_file = tmp_path / "safety_gate.py"
    other_file.write_text("other content", encoding="utf-8")
    monkeypatch.setattr(safety, "_INTEGRITY_FILES", (fake_file, other_file))

    safety.generate_integrity_manifest()
    v = safety.check_runtime_integrity()
    assert v.safe

    fake_file.write_text("modified content — bypass injected", encoding="utf-8")
    v = safety.check_runtime_integrity()
    assert not v.safe
    assert v.category == "TOS_CIRCUMVENTION"


# ── Corpus tamper detection feeds the WAL (Layer 4 + Layer 6 crossover) ─────


def test_corpus_tamper_is_wal_logged_as_tos_circumvention(_isolated_state):
    engine = safety.SafetyEngine(mode="strict", subject_id="subj-h")
    entry = {"id": "sample-3", "code": "def foo(): return 1"}
    engine.sign_corpus_entry(entry)
    entry["code"] = "def foo(): return 2"  # mutate after signing, without re-signing

    with pytest.raises(safety.CorpusTamperError):
        engine.verify_corpus_entry(entry)

    state = safety.load_escalation("subj-h")
    assert state.violation_count == 1
    assert state.history[-1]["category"] == "TOS_CIRCUMVENTION"
