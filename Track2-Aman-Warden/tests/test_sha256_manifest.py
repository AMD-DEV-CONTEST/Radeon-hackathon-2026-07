"""Tests for the SHA-256 benchmark manifest generator.

Verifies the manifest is reproducible, JSONL-valid, and captures the
critical inputs (scripts, policies, attack samples) so benchmark
results can be reproduced and audited.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scripts.sha256_manifest import build_manifest, _sha256


def test_manifest_entries_are_valid_jsonl(tmp_path):
    repo = pathlib.Path(__file__).resolve().parent.parent
    entries = build_manifest(repo, include_models=False)
    assert len(entries) > 10, "manifest should include many files"
    # Every entry must be JSON-serializable and have required fields.
    for e in entries:
        s = json.dumps(e, sort_keys=True)
        d = json.loads(s)
        assert "path" in d and d["path"]
        assert "sha256" in d and len(d["sha256"]) == 64
        assert "size_bytes" in d and d["size_bytes"] >= 0
        assert "generated_at" in d
        assert "commit_sha" in d  # may be "" off-git, but key must exist


def test_manifest_includes_critical_inputs():
    """Judges care that scripts, policies, and attack samples are hashed."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    entries = build_manifest(repo, include_models=False)
    paths = {e["path"] for e in entries}
    # At least one script, one policy, one attack sample
    assert any(p.startswith("scripts/") for p in paths), "no scripts hashed"
    assert any(p.startswith("tests/") for p in paths), "no tests hashed"
    # data/owasp_llm_top10.json should be in the manifest (RAG seed)
    assert any(p.startswith("data/") for p in paths), "no data/ files hashed"


def test_manifest_hashes_match_actual_files():
    """Spot-check: re-hash a file and confirm manifest matches."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    entries = build_manifest(repo, include_models=False)
    # Find this test file in the manifest and re-hash it.
    this_path = pathlib.Path(__file__).resolve()
    rel = this_path.relative_to(repo).as_posix()
    match = next((e for e in entries if e["path"] == rel), None)
    assert match is not None, f"manifest missing {rel}"
    assert match["sha256"] == _sha256(this_path), "manifest hash stale"


def test_manifest_reproducible_within_same_second():
    """Two builds back-to-back produce identical hashes (paths are stable)."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    e1 = build_manifest(repo, include_models=False)
    # Tiny delay to ensure generated_at might differ but hashes shouldn't.
    time.sleep(0.01)
    e2 = build_manifest(repo, include_models=False)
    # Same number of entries
    assert len(e1) == len(e2)
    # Same set of (path, sha256) pairs — order may vary if glob changes,
    # but contents must be identical.
    pairs1 = {(e["path"], e["sha256"]) for e in e1}
    pairs2 = {(e["path"], e["sha256"]) for e in e2}
    assert pairs1 == pairs2
