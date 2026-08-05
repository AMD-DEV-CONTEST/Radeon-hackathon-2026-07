"""Tests for patch_body_hash (binding helper for the apply gate)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.repair.patch_body_hash import compute

_REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "REAL_APPROVAL_DIFF_BODY_CONTENT_BINDING_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_approval_diff_body_content_binding"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def test_same_entries_produce_same_hash():
    e1 = [{"operation": "replace_file", "path": "src/a.py", "new_content": "x"}]
    e2 = [{"operation": "replace_file", "path": "src/a.py", "new_content": "x"}]
    assert compute(e1).hex_digest == compute(e2).hex_digest


def test_different_bodies_different_hash():
    e1 = [{"operation": "replace_file", "path": "src/a.py", "new_content": "x"}]
    e2 = [{"operation": "replace_file", "path": "src/a.py", "new_content": "y"}]
    assert compute(e1).hex_digest != compute(e2).hex_digest


def test_different_paths_different_hash():
    e1 = [{"operation": "replace_file", "path": "src/a.py", "new_content": "x"}]
    e2 = [{"operation": "replace_file", "path": "src/b.py", "new_content": "x"}]
    assert compute(e1).hex_digest != compute(e2).hex_digest


def test_order_independence():
    """Two orderings of the same entries produce the same hash."""
    a = [
        {"operation": "replace_file", "path": "src/a.py", "new_content": "x"},
        {"operation": "replace_file", "path": "src/b.py", "new_content": "y"},
    ]
    b = list(reversed(a))
    assert compute(a).hex_digest == compute(b).hex_digest


def test_path_normalization():
    e1 = [{"operation": "replace_file", "path": "src/a.py", "new_content": "x"}]
    e2 = [{"operation": "replace_file", "path": "src\\a.py", "new_content": "x"}]
    e3 = [{"operation": "replace_file", "path": "/src/a.py", "new_content": "x"}]
    assert compute(e1).hex_digest == compute(e2).hex_digest
    # Absolute path is rejected.
    assert compute(e3).hex_digest == ""
    assert "absolute" in compute(e3).rejected_reason


def test_dotdot_path_rejected():
    e = [{"operation": "replace_file", "path": "../escape", "new_content": "x"}]
    r = compute(e)
    assert r.hex_digest == ""
    assert "'..'" in r.rejected_reason


def test_nul_byte_in_body_rejected():
    e = [{"operation": "replace_file", "path": "a", "new_content": "ok\x00bad"}]
    r = compute(e)
    assert r.hex_digest == ""
    assert "NUL" in r.rejected_reason


def test_unsupported_operation_rejected():
    e = [{"operation": "rm_rf", "path": "a", "new_content": ""}]
    r = compute(e)
    assert r.hex_digest == ""
    assert "rm_rf" in r.rejected_reason


def test_empty_entries_invalid():
    r = compute([])
    assert r.hex_digest == ""
    assert "no accepted entries" in r.rejected_reason


def test_record_serializes_to_json():
    r = compute([{"operation": "replace_file", "path": "a", "new_content": "x"}])
    assert r.is_valid
    payload = {"hex_digest": r.hex_digest, "accepted_count": r.accepted_count}
    json.dumps(payload)


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_APPROVAL_DIFF_BODY_CONTENT_BINDING_LOCK_001"
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligibility_opened") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_APPROVAL_DIFF_BODY_CONTENT_BINDING_LOCK_001" in ids
