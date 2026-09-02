"""Tests for IDE_WORKSPACE_OPEN_FLOW_LOCK_001."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

flow_mod = importlib.import_module("ide.workspace_open_flow")
rec_mod = importlib.import_module("ide.workspace_open_record")

IDEWorkspaceOpenFlow = flow_mod.IDEWorkspaceOpenFlow
IDE_WORKSPACE_OPEN_STATUS_TOKENS = rec_mod.IDE_WORKSPACE_OPEN_STATUS_TOKENS

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "IDE_WORKSPACE_OPEN_FLOW_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "ide_workspace_open_flow"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(IDE_WORKSPACE_OPEN_STATUS_TOKENS)


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
    return out


def test_status_tokens_match_expected_set():
    expected = {
        "WORKSPACE_OPEN_READY",
        "WORKSPACE_OPEN_BLOCKED_PATH_ESCAPE",
        "WORKSPACE_OPEN_BLOCKED_UNSUPPORTED_REPO",
        "WORKSPACE_OPEN_VERIFIER_AVAILABLE",
        "WORKSPACE_OPEN_VERIFIER_MISSING",
        "WORKSPACE_OPEN_SOURCE_UNCHANGED",
        "WORKSPACE_OPEN_BLOCKED_NOT_A_DIRECTORY",
    }
    assert set(STATUS_TOKENS) == expected


def test_python_fixture_opens_ready():
    f = IDEWorkspaceOpenFlow()
    rec = f.open(FIXTURES / "python_broken")
    assert rec.decision == "WORKSPACE_OPEN_READY"
    assert rec.adapter_name == "Python"
    assert rec.build_system_id == "pip"
    assert "WORKSPACE_OPEN_SOURCE_UNCHANGED" in rec.statuses_seen


def test_rust_fixture_opens_ready():
    rec = IDEWorkspaceOpenFlow().open(FIXTURES / "rust_broken")
    assert rec.decision == "WORKSPACE_OPEN_READY"
    assert rec.adapter_name == "Rust"


def test_unsupported_fixture_blocks():
    rec = IDEWorkspaceOpenFlow().open(FIXTURES / "unsupported_repo")
    assert rec.decision == "WORKSPACE_OPEN_BLOCKED_UNSUPPORTED_REPO"


@pytest.mark.parametrize("bad", ["../etc/passwd", "..\\..\\system32", ""])
def test_path_escape_blocked(bad):
    rec = IDEWorkspaceOpenFlow().open(bad)
    assert rec.decision == "WORKSPACE_OPEN_BLOCKED_PATH_ESCAPE"


def test_nonexistent_path_blocked(tmp_path):
    rec = IDEWorkspaceOpenFlow().open(tmp_path / "does_not_exist")
    assert rec.decision == "WORKSPACE_OPEN_BLOCKED_NOT_A_DIRECTORY"


def test_file_path_blocked(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x")
    rec = IDEWorkspaceOpenFlow().open(f)
    assert rec.decision == "WORKSPACE_OPEN_BLOCKED_NOT_A_DIRECTORY"


def test_open_does_not_mutate_workspace():
    ws = FIXTURES / "python_broken"
    before = _hash_tree(ws)
    IDEWorkspaceOpenFlow().open(ws)
    assert _hash_tree(ws) == before


def test_modules_do_not_import_subprocess_or_urllib():
    for fname in ("workspace_open_flow.py", "workspace_open_record.py"):
        src = (_REPO_ROOT / "scripts" / "ide" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src
        assert "import urllib" not in src


def test_record_json_round_trip():
    rec = IDEWorkspaceOpenFlow().open(FIXTURES / "python_broken")
    parsed = json.loads(rec.to_json())
    assert parsed["source_unchanged"] is True


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "IDE_WORKSPACE_OPEN_FLOW_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "IDE_WORKSPACE_OPEN_FLOW_LOCK_001" in ids
