"""Tests for scripts/determinex_pb_absorb.py's quality gate and merge-on-write safety.

The merge-on-write test reproduces the exact 2026-07-19 data-loss bug: a long-running absorb
pass holds build_knowledge.json in memory for its whole runtime; a naive flush blindly
overwrites the file, silently erasing anything another writer added in the meantime. Two real
corpus findings were lost this way in the same session that fixed it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_pb_absorb as absorb  # noqa: E402


def test_bound_and_write_preserves_a_key_added_concurrently_by_another_writer(
    tmp_path, monkeypatch
):
    kn_path = tmp_path / "build_knowledge.json"
    original = {"existing_entry": {"a": 1}, "learned_classes": {}, "absorbed_sources": []}
    kn_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(absorb, "KN", kn_path)

    # absorb loaded a snapshot BEFORE another writer added a new key to disk.
    stale_kn = json.loads(kn_path.read_text(encoding="utf-8"))
    stale_kn["learned_classes"]["new_learned"] = {"detect": "d", "fix": "f", "verified": True}

    # the "other writer" mutates the file while absorb still holds its stale snapshot.
    on_disk = json.loads(kn_path.read_text(encoding="utf-8"))
    on_disk["CONCURRENT_FINDING_MUST_SURVIVE"] = {"proof": True}
    kn_path.write_text(json.dumps(on_disk), encoding="utf-8")

    # absorb's periodic checkpoint flush must not clobber the concurrent write.
    absorb._bound_and_write(stale_kn, stale_kn["learned_classes"], dry_run=False)

    result = json.loads(kn_path.read_text(encoding="utf-8"))
    assert result["CONCURRENT_FINDING_MUST_SURVIVE"] == {"proof": True}
    assert "new_learned" in result["learned_classes"]  # this run's own contribution still lands


def test_bound_and_write_dry_run_never_touches_disk(tmp_path, monkeypatch):
    kn_path = tmp_path / "build_knowledge.json"
    kn_path.write_text(
        json.dumps({"learned_classes": {}, "absorbed_sources": []}), encoding="utf-8"
    )
    monkeypatch.setattr(absorb, "KN", kn_path)
    before = kn_path.read_text(encoding="utf-8")
    absorb._bound_and_write({"learned_classes": {}}, {"x": {}}, dry_run=True)
    assert kn_path.read_text(encoding="utf-8") == before


def test_quality_gate_rejects_requirement_voice_detect():
    # "incorrect" satisfies _SYMPTOM (failure-shaped vocabulary) but the sentence carries no
    # _HARD_FAIL marker (no error/fail/traceback/rc=N/etc) and IS requirement voice ("should
    # print") -- a paraphrased spec requirement, not an observed failure, must be rejected.
    assert (
        absorb._quality_gate(
            "The version output format is incorrect: the tool should print semantic version strings",
            "Ensure the tool prints proper semantic version strings",
        )
        == "requirement-not-failure"
    )


def test_quality_gate_rejects_paraphrase_loop():
    assert (
        absorb._quality_gate(
            "Test failures related to every sort with every direction",
            "Ensure the tool supports both ascending and descending sorts for each column",
        )
        is not None
    )


def test_quality_gate_accepts_genuine_symptom_fix_pair():
    assert (
        absorb._quality_gate(
            "Error: /workspace/executable is a symlink",
            "Run image preflight and ensure compile.sh produces a real executable file, not a symlink.",
        )
        is None
    )
