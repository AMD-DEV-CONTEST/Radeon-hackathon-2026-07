"""Tests for BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("repair.build_adapter_backed_verifier_selection")
rec_mod = importlib.import_module("repair.build_adapter_backed_verifier_selection_record")

select_verifier = mod.select_verifier
TOKENS = rec_mod.BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_STATUS_TOKENS
BuildAdapterBackedVerifierSelectionRecord = rec_mod.BuildAdapterBackedVerifierSelectionRecord

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "build_adapter_backed_verifier_selection"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "BUILD_ADAPTER_VERIFIER_SELECTED",
        "BUILD_ADAPTER_VERIFIER_BLOCKED_UNSUPPORTED_REPO",
        "BUILD_ADAPTER_VERIFIER_BLOCKED_NO_TEST_COMMAND",
        "BUILD_ADAPTER_VERIFIER_BLOCKED_HARDENED_RUNNER",
        "BUILD_ADAPTER_VERIFIER_BLOCKED_WORKSPACE_MISSING",
    }
)


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_missing_workspace_blocks(tmp_path):
    r = select_verifier(workspace=tmp_path / "does-not-exist")
    assert r.decision == "BUILD_ADAPTER_VERIFIER_BLOCKED_WORKSPACE_MISSING"


def test_empty_workspace_blocks_unsupported(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = select_verifier(workspace=ws)
    assert r.decision == "BUILD_ADAPTER_VERIFIER_BLOCKED_UNSUPPORTED_REPO"


def test_python_fixture_selected(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (ws / "tests").mkdir()
    (ws / "tests" / "test_x.py").write_text("def test_x(): pass\n", encoding="utf-8")
    r = select_verifier(workspace=ws)
    assert r.decision == "BUILD_ADAPTER_VERIFIER_SELECTED"
    assert r.build_system_id == "pip"
    assert r.test_framework_id == "pytest"
    assert "pytest" in r.verifier_command
    assert r.hardened_runner == "intake.hardened_runner"


def test_rust_fixture_selected(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "Cargo.toml").write_text(
        "[package]\nname='x'\nversion='0.1.0'\nedition='2021'\n",
        encoding="utf-8",
    )
    (ws / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    r = select_verifier(workspace=ws)
    assert r.decision == "BUILD_ADAPTER_VERIFIER_SELECTED"
    assert r.build_system_id == "cargo"
    assert r.verifier_command == ("cargo", "test")


def test_go_fixture_selected(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "go.mod").write_text("module example.com/x\n", encoding="utf-8")
    (ws / "main.go").write_text(
        "package main\nfunc main() {}\n",
        encoding="utf-8",
    )
    r = select_verifier(workspace=ws)
    assert r.decision == "BUILD_ADAPTER_VERIFIER_SELECTED"
    assert r.build_system_id == "go"
    assert r.verifier_command == ("go", "test")


def test_record_invariants(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    r = select_verifier(workspace=ws)
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False


def test_module_does_not_execute_verifier():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    # The module derives the command; it never runs it.
    for forbidden in (
        "subprocess.Popen",
        "subprocess.run",
        "subprocess.call",
        "os.system",
    ):
        assert forbidden not in src
    # Hardened runner is referenced as a module name string only; we
    # check we never invoke its run().
    assert "hardened_run(" not in src
    assert "hardened_runner.run(" not in src


def test_record_serializes_safely(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    r = select_verifier(workspace=ws)
    d = r.to_dict()
    json.dumps(d)
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("verifier_command_executed") is False
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligibility_opened") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_LOCK_001" in ids
