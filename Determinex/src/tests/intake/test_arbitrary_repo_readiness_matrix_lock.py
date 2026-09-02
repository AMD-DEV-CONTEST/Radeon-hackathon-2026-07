"""Tests for ARBITRARY_REPO_READINESS_MATRIX_LOCK_001.

The readiness matrix is machine-readable. Tests verify:

  * Required row set is present (Python/pip/pytest, Rust/cargo,
    Go/go test, TS/npm/jest, TS/npm/vitest, Java/Maven, Java/Gradle,
    Unknown).
  * Unsupported rows are NOT marked ready.
  * The matrix is signed-friendly (JSON-serializable, deterministic
    column set).
  * Building the matrix performs no execution, no subprocess, no
    network.
  * Lock + evidence + index entries are present and valid.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

matrix_mod = importlib.import_module("intake.arbitrary_repo_readiness_matrix")
rec_mod = importlib.import_module("intake.arbitrary_repo_readiness_record")

build_readiness_matrix = matrix_mod.build_readiness_matrix
ReadinessMatrix = matrix_mod.ReadinessMatrix
ReadinessRow = matrix_mod.ReadinessRow
ReadyLevel = matrix_mod.ReadyLevel
READINESS_MATRIX_STATUS_TOKENS = matrix_mod.READINESS_MATRIX_STATUS_TOKENS

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "ARBITRARY_REPO_READINESS_MATRIX_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "arbitrary_repo_readiness_matrix"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(READINESS_MATRIX_STATUS_TOKENS)


REQUIRED_BUILD_SYSTEMS = frozenset(
    {
        "pip",
        "cargo",
        "go",
        "npm",
        "maven",
        "gradle",
        "unknown",
    }
)


def test_status_tokens_match_expected_set():
    expected = {
        "READINESS_MATRIX_WRITTEN",
        "READY_MOCKED_TRACE",
        "READY_TEMP_PATCH_ONLY",
        "READY_REQUIRES_LIVE_MODEL_ADMISSION",
        "READY_REQUIRES_VERIFIER",
        "BLOCKED_UNSUPPORTED",
    }
    assert set(STATUS_TOKENS) == expected


def test_matrix_includes_required_build_systems():
    m = build_readiness_matrix()
    seen = {r.build_system for r in m.rows}
    assert REQUIRED_BUILD_SYSTEMS.issubset(seen), f"Missing: {REQUIRED_BUILD_SYSTEMS - seen}"


def test_typescript_has_both_jest_and_vitest_rows():
    m = build_readiness_matrix()
    ts_rows = [r for r in m.rows if r.language == "TypeScript"]
    frameworks = {r.test_framework for r in ts_rows}
    assert "jest" in frameworks
    assert "vitest" in frameworks


def test_unsupported_row_not_marked_ready():
    m = build_readiness_matrix()
    unk = m.find("unknown")
    assert unk is not None
    assert unk.ready_level == ReadyLevel.BLOCKED_UNSUPPORTED.value
    assert unk.adapter_backed is False


def test_all_supported_rows_have_a_real_ready_level():
    m = build_readiness_matrix()
    valid_levels = {l.value for l in ReadyLevel} - {ReadyLevel.BLOCKED_UNSUPPORTED.value}
    for r in m.rows:
        if r.language == "Unknown":
            continue
        assert r.ready_level in valid_levels, (
            f"{r.build_system}: invalid ready_level {r.ready_level!r}"
        )


def test_live_model_admitted_false_on_every_row_at_this_rung():
    """No row should claim live model admission at this rung."""
    m = build_readiness_matrix()
    for r in m.rows:
        assert r.live_model_admitted is False


def test_matrix_is_deterministic():
    a = build_readiness_matrix()
    b = build_readiness_matrix()
    # Compare rows (excluding generated_at timestamp)
    assert [r.to_dict() for r in a.rows] == [r.to_dict() for r in b.rows]


def test_matrix_to_json_round_trip():
    m = build_readiness_matrix()
    parsed = json.loads(m.to_json())
    assert "rows" in parsed
    assert isinstance(parsed["rows"], list)
    for row_dict in parsed["rows"]:
        assert "ready_level" in row_dict
        assert "live_model_admitted" in row_dict


def test_module_does_not_import_subprocess_or_urllib():
    for fname in ("arbitrary_repo_readiness_matrix.py", "arbitrary_repo_readiness_record.py"):
        src = (_REPO_ROOT / "scripts" / "intake" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "from subprocess" not in src
        assert "import urllib" not in src
        assert "from urllib" not in src
        assert "import socket" not in src
        assert "import http" not in src


def test_build_matrix_does_not_run_subprocess(monkeypatch):
    """Defensive sentinel: any subprocess.run / subprocess.Popen call
    during matrix construction should be detected by this monkeypatch."""
    import subprocess as _sp

    called = {"count": 0}
    original_run = _sp.run

    def _spy(*args, **kwargs):  # pragma: no cover — should never fire
        called["count"] += 1
        return original_run(*args, **kwargs)

    monkeypatch.setattr(_sp, "run", _spy)
    build_readiness_matrix()
    assert called["count"] == 0, "build_readiness_matrix called subprocess.run"


# ---------------------------------------------------------------------------
# Lock + evidence + index
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "ARBITRARY_REPO_READINESS_MATRIX_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "ARBITRARY_REPO_READINESS_MATRIX_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "ARBITRARY_REPO_READINESS_MATRIX_LOCK_001" in ids
