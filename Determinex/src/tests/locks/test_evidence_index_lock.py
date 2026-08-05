from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from evidence_index import _manifest_paths, generate_index, validate_index  # noqa: E402


def test_evidence_index_includes_all_lock_and_drain_manifests():
    index = generate_index(_ROOT)
    ids = {entry["evidence_id"] for entry in index["entries"]}
    expected = {p.stem for p in _manifest_paths(_ROOT, "locks/sentinel")} | {
        p.stem for p in _manifest_paths(_ROOT, "locks/drain")
    }

    assert expected <= ids


def test_evidence_entries_have_required_release_fields():
    index = generate_index(_ROOT)

    assert index["validation_errors"] == []
    for entry in index["entries"]:
        assert entry["manifest_path"]
        assert entry["test_count"] > 0
        assert entry["full_suite_count"] > 0
        assert entry["reproduction_command"]
        assert entry["commit"]
        assert entry["proves"]
        assert entry["does_not_prove"]


def test_evidence_manifest_paths_exist():
    index = generate_index(_ROOT)

    for entry in index["entries"]:
        assert (_ROOT / entry["manifest_path"]).is_file()


def test_evidence_index_validation_catches_missing_fields():
    broken = {
        "schema_version": "determinex-evidence-index-v1",
        "entries": [
            {
                "evidence_id": "BROKEN_LOCK",
                "kind": "sentinel_lock",
                "manifest_path": "",
                "test_count": 0,
                "full_suite_count": 0,
                "reproduction_command": "",
                "commit": "",
                "proves": "",
                "does_not_prove": "",
            }
        ],
    }

    errors = validate_index(broken, root=_ROOT)

    assert "BROKEN_LOCK:missing_manifest_path" in errors
    assert "BROKEN_LOCK:test_count_not_positive" in errors
    assert "BROKEN_LOCK:full_suite_count_not_positive" in errors


def test_evidence_index_json_serializable():
    index = generate_index(_ROOT)

    encoded = json.dumps(index, sort_keys=True)

    assert "EVIDENCE_INDEX_LOCK_001" in encoded
    assert "schema_version" in encoded
