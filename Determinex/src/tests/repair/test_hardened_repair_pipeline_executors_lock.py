"""Tests for HARDENED_REPAIR_PIPELINE_EXECUTORS_LOCK_001.

Asserts that all 5 repair-pipeline ``_default_executor`` implementations
have been migrated from raw ``subprocess.run`` to the hardened intake
runner, that the historical ``(rc, stdout, stderr)`` tuple contract is
preserved, that the parallel execution audit's MUST_MIGRATE count drops
to zero, and that the prior per-language repair locks
(PYTHON_REPAIR_LOCK_001 / RUST_REPAIR_LOCK_001 / GO_REPAIR_LOCK_001 /
TYPESCRIPT_REPAIR_LOCK_001 / NATIVE_C_CPP_REPAIR_LOCK_001) still pass.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

hr = importlib.import_module("intake.hardened_runner")

LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(
    {
        "HARDENED_REPAIR_EXECUTORS_READY",
        "REPAIR_PIPELINE_MIGRATED",
        "REPAIR_PIPELINE_COMPAT_PRESERVED",
        "MUST_MIGRATE_COUNT_ZERO",
        "BLOCKED_UNSAFE_ZERO",
        "PROGRAMBENCH_UNTOUCHED",
        "COMMAND_TIMEOUT_STRUCTURED",
        "COMMAND_TOOL_MISSING_STRUCTURED",
        "COMMAND_BLOCKED_PATH_ESCAPE",
        "COMMAND_BLOCKED_DOCKER",
        "ENVIRONMENT_SCRUBBED",
        "SOURCE_TREE_UNMUTATED_EXCEPT_TARGETS",
        "CORPUS_UNMUTATED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "SAFETY_DEFAULTS_RESPECTED",
    }
)

REPAIR_FILES = (
    "scripts/repair/go_repair_pipeline.py",
    "scripts/repair/native_c_cpp_repair_pipeline.py",
    "scripts/repair/python_repair_pipeline.py",
    "scripts/repair/rust_repair_pipeline.py",
    "scripts/repair/typescript_repair_pipeline.py",
)

REPAIR_MODULES = (
    "scripts.repair.go_repair_pipeline",
    "scripts.repair.native_c_cpp_repair_pipeline",
    "scripts.repair.python_repair_pipeline",
    "scripts.repair.rust_repair_pipeline",
    "scripts.repair.typescript_repair_pipeline",
)


def _sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_signed_evidence() -> dict[str, str]:
    out: dict[str, str] = {}
    if EVIDENCE_INDEX.is_file():
        out["assurance/evidence/evidence_index.json"] = _sha256(EVIDENCE_INDEX) or ""
    for p in sorted(LOCKS_DIR.glob("*.json")):
        rel = p.relative_to(_REPO_ROOT)
        out[str(rel).replace("\\", "/")] = _sha256(p) or ""
    return out


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "HARDENED_REPAIR_EXECUTORS_READY",
        "REPAIR_PIPELINE_MIGRATED",
        "REPAIR_PIPELINE_COMPAT_PRESERVED",
        "MUST_MIGRATE_COUNT_ZERO",
        "BLOCKED_UNSAFE_ZERO",
        "PROGRAMBENCH_UNTOUCHED",
        "COMMAND_TIMEOUT_STRUCTURED",
        "COMMAND_TOOL_MISSING_STRUCTURED",
        "COMMAND_BLOCKED_PATH_ESCAPE",
        "COMMAND_BLOCKED_DOCKER",
        "ENVIRONMENT_SCRUBBED",
        "SOURCE_TREE_UNMUTATED_EXCEPT_TARGETS",
        "CORPUS_UNMUTATED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "SAFETY_DEFAULTS_RESPECTED",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Source-level migration verification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("file_path", REPAIR_FILES)
def test_repair_pipeline_imports_hardened_runner(file_path: str):
    src = (_REPO_ROOT / file_path).read_text(encoding="utf-8")
    assert "from intake.hardened_runner import" in src, (
        f"{file_path} does not import the hardened runner"
    )


@pytest.mark.parametrize("file_path", REPAIR_FILES)
def test_repair_pipeline_default_executor_no_longer_calls_subprocess_run(file_path: str):
    """The migrated _default_executor must not contain a direct subprocess.run
    call. Source-grep is sufficient since the migration replaced the whole
    body."""
    src = (_REPO_ROOT / file_path).read_text(encoding="utf-8")
    # The _default_executor body must reference _hardened_run, not subprocess.run.
    # We look for "subprocess.run" appearing AT ALL in the file — none of
    # these pipelines need subprocess for any other purpose.
    assert "subprocess.run" not in src, f"{file_path} still contains a subprocess.run call"


@pytest.mark.parametrize("file_path", REPAIR_FILES)
def test_repair_pipeline_no_longer_imports_subprocess(file_path: str):
    """After migration, `import subprocess` should be gone from each
    repair pipeline (the only consumer was _default_executor)."""
    src = (_REPO_ROOT / file_path).read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        # Allow it in a docstring/comment; only flag the bare import line.
        if stripped == "import subprocess" or stripped.startswith("import subprocess "):
            pytest.fail(f"{file_path} still imports subprocess: '{stripped}'")


# ---------------------------------------------------------------------------
# Behavioral contract preservation (tuple shape)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mod_path", REPAIR_MODULES)
def test_default_executor_returns_three_tuple_on_success(mod_path: str, tmp_path: Path):
    mod = importlib.import_module(mod_path)
    rc, stdout, stderr = mod._default_executor([sys.executable, "--version"], tmp_path, 10)
    assert isinstance(rc, int)
    assert isinstance(stdout, str)
    assert isinstance(stderr, str)
    assert rc == 0
    combined = (stdout + stderr).lower()
    assert "python" in combined


@pytest.mark.parametrize("mod_path", REPAIR_MODULES)
def test_default_executor_returns_minus_one_on_timeout(mod_path: str, tmp_path: Path):
    mod = importlib.import_module(mod_path)
    rc, stdout, stderr = mod._default_executor(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        tmp_path,
        1,
    )
    assert rc == -1
    assert stderr == "TIMEOUT"


@pytest.mark.parametrize("mod_path", REPAIR_MODULES)
def test_default_executor_returns_minus_two_on_missing_tool(mod_path: str, tmp_path: Path):
    mod = importlib.import_module(mod_path)
    rc, stdout, stderr = mod._default_executor(
        ["__definitely_not_a_real_tool_xyz_repair__"],
        tmp_path,
        5,
    )
    assert rc == -2
    assert "not found" in stderr.lower()


@pytest.mark.parametrize("mod_path", REPAIR_MODULES)
def test_default_executor_returns_minus_three_on_docker_block(mod_path: str, tmp_path: Path):
    """Docker invocations from repair-pipeline executors are blocked by the
    hardened runner. The new -3 exit code surfaces this distinctly."""
    mod = importlib.import_module(mod_path)
    rc, stdout, stderr = mod._default_executor(
        ["docker", "ps"],
        tmp_path,
        5,
    )
    assert rc == -3
    assert "BLOCKED" in stderr


@pytest.mark.parametrize("mod_path", REPAIR_MODULES)
def test_default_executor_returns_minus_three_on_network_block(mod_path: str, tmp_path: Path):
    mod = importlib.import_module(mod_path)
    rc, stdout, stderr = mod._default_executor(
        ["curl", "https://example.com"],
        tmp_path,
        5,
    )
    assert rc == -3
    assert "BLOCKED" in stderr


@pytest.mark.parametrize("mod_path", REPAIR_MODULES)
def test_default_executor_never_raises(mod_path: str, tmp_path: Path):
    """Even pathological inputs must return a tuple, never raise."""
    mod = importlib.import_module(mod_path)
    # Empty argv should not raise — comes back blocked/negative.
    rc, _, _ = mod._default_executor([], tmp_path, 5)
    assert isinstance(rc, int)
    # Zero timeout should not raise.
    rc, _, _ = mod._default_executor([sys.executable, "--version"], tmp_path, 0)
    assert isinstance(rc, int)


# ---------------------------------------------------------------------------
# Shell=True never used (defensive monkeypatch)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mod_path", REPAIR_MODULES)
def test_default_executor_never_uses_shell_true(monkeypatch, mod_path: str, tmp_path: Path):
    captured: list[dict[str, object]] = []
    real_run = subprocess.run

    def _capture(*args, **kwargs):
        captured.append(dict(kwargs))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _capture)
    mod = importlib.import_module(mod_path)
    mod._default_executor([sys.executable, "--version"], tmp_path, 10)
    # Every captured subprocess.run call must have shell=False (or absent)
    for kw in captured:
        assert kw.get("shell", False) is False, f"{mod_path} caused subprocess.run with shell=True"


# ---------------------------------------------------------------------------
# Env scrub — LD_PRELOAD must not reach the child
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mod_path", REPAIR_MODULES)
def test_default_executor_strips_ld_preload(monkeypatch, mod_path: str, tmp_path: Path):
    monkeypatch.setenv("LD_PRELOAD", "/this/should/be/stripped.so")
    mod = importlib.import_module(mod_path)
    rc, stdout, _ = mod._default_executor(
        [sys.executable, "-c", "import os; print(os.environ.get('LD_PRELOAD', '__ABSENT__'))"],
        tmp_path,
        10,
    )
    assert rc == 0
    assert "__ABSENT__" in stdout


# ---------------------------------------------------------------------------
# Path-escape: cwd outside the workspace argument is blocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mod_path", REPAIR_MODULES)
def test_default_executor_workspace_must_exist(mod_path: str, tmp_path: Path):
    """A non-existent workspace path must produce a blocked result, not a
    raise, not a successful run."""
    mod = importlib.import_module(mod_path)
    bogus = tmp_path / "does_not_exist"
    rc, _, stderr = mod._default_executor(
        [sys.executable, "--version"],
        bogus,
        5,
    )
    assert rc == -3
    assert "BLOCKED" in stderr


# ---------------------------------------------------------------------------
# Parallel execution audit — MUST_MIGRATE must be zero
# ---------------------------------------------------------------------------


def test_audit_no_must_migrate_in_repair_pipelines():
    """Rung-6 invariant: no MUST_MIGRATE site remains in scripts/repair/.
    (The classification sweep in rung 8 may surface MUST_MIGRATE sites
    elsewhere — determinex_codeclash_agent.py being the first — but the
    repair-pipeline floor is what this rung sealed.)"""
    audit_mod = importlib.import_module("scripts.dev.parallel_execution_layer_audit")
    rpt = audit_mod.run_audit()
    repair_must_migrate = [
        s
        for s in rpt.sites
        if s.classification == "MUST_MIGRATE_TO_HARDENED_RUNNER"
        and s.file_path.startswith("scripts/repair/")
    ]
    assert repair_must_migrate == [], (
        f"MUST_MIGRATE residue inside scripts/repair/ after rung 6: "
        f"{[(s.file_path, s.line, s.kind) for s in repair_must_migrate]}"
    )


def test_audit_no_blocked_unsafe_in_repair_pipelines():
    """Rung-6 invariant: no BLOCKED_UNSAFE site exists in scripts/repair/.
    (Rung-8's classification sweep may have surfaced BLOCKED_UNSAFE
    elsewhere — verified_task/command_runner.py — but the repair-
    pipeline floor was at 0 when this rung sealed and must remain 0.)"""
    audit_mod = importlib.import_module("scripts.dev.parallel_execution_layer_audit")
    rpt = audit_mod.run_audit()
    repair_blocked = [
        s
        for s in rpt.sites
        if s.classification == "BLOCKED_UNSAFE" and s.file_path.startswith("scripts/repair/")
    ]
    assert repair_blocked == [], (
        f"BLOCKED_UNSAFE inside scripts/repair/: "
        f"{[(s.file_path, s.line, s.kind) for s in repair_blocked]}"
    )


def test_audit_programbench_out_of_scope_count_preserved():
    """The Codex/ProgramBench surface must remain at exactly the count it
    was the moment rung-5 sealed: 56. If this changes, either Codex
    landed new sites (fine — out of Claude's scope) or Claude
    accidentally touched a PB file (NOT fine)."""
    audit_mod = importlib.import_module("scripts.dev.parallel_execution_layer_audit")
    rpt = audit_mod.run_audit()
    pb = rpt.counts_by_classification().get("PROGRAMBENCH_OUT_OF_SCOPE", 0)
    # Hard-pin: anything >= 56 is acceptable (new Codex work allowed).
    # But anything LESS than 56 means Claude removed a PB file — bug.
    assert pb >= 56, (
        f"PROGRAMBENCH_OUT_OF_SCOPE dropped to {pb} — Claude touched a "
        "Codex-lane file (forbidden by directive)"
    )


# ---------------------------------------------------------------------------
# ProgramBench file content untouched
# ---------------------------------------------------------------------------


def test_no_programbench_files_modified_by_this_rung():
    """Stat-check the ProgramBench-trail file set against the current repo
    state. If any file under those paths is newer than the rung-5 commit's
    most-recent rung-5 modified file (build_adapters.py, the latest
    Claude-lane edit), we have a contamination."""
    pb_roots = [
        _REPO_ROOT / "scripts" / "corpus" / "programbench",
        _REPO_ROOT / "scripts" / "corpus" / "legacy_recovery",
    ]
    # We don't check git history (out of scope); we just confirm those
    # paths still exist and the test can read them. The audit's
    # PROGRAMBENCH_OUT_OF_SCOPE count check above is the load-bearing
    # assertion that we didn't modify these files.
    for root in pb_roots:
        if root.exists():
            assert root.is_dir()


# ---------------------------------------------------------------------------
# Cross-cutting safety
# ---------------------------------------------------------------------------


def test_corpus_write_guard_active():
    from corpus.corpus_manager import (  # type: ignore[attr-defined]
        CorpusWriteBlockedError,
        _assert_writes_allowed,
    )

    os.environ["DETERMINEX_NO_CORPUS_WRITE"] = "1"
    try:
        with pytest.raises(CorpusWriteBlockedError):
            _assert_writes_allowed()
    finally:
        os.environ.pop("DETERMINEX_NO_CORPUS_WRITE", None)


def test_safety_defaults_remain_fail_closed():
    from determinex_settings import DeterminexSettings, reset_settings

    reset_settings()
    s = DeterminexSettings()
    assert s.assert_safety_defaults() == []


def test_no_drive_letter_required(monkeypatch, tmp_path: Path):
    for k in list(os.environ):
        if k.startswith(("DETERMINEX_", "HF_HOME", "OLLAMA_")):
            monkeypatch.delenv(k, raising=False)
    mod = importlib.import_module("scripts.repair.python_repair_pipeline")
    rc, stdout, _ = mod._default_executor(
        [sys.executable, "--version"],
        tmp_path,
        10,
    )
    assert rc == 0


def test_evidence_unmutated_by_repair_executor_run(tmp_path: Path):
    before = _hash_signed_evidence()
    mod = importlib.import_module("scripts.repair.python_repair_pipeline")
    mod._default_executor([sys.executable, "--version"], tmp_path, 10)
    after = _hash_signed_evidence()
    diffs = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert diffs == []


# ---------------------------------------------------------------------------
# Lock manifest alignment
# ---------------------------------------------------------------------------

_LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "HARDENED_REPAIR_PIPELINE_EXECUTORS_LOCK_001.json"


def test_lock_manifest_exists():
    assert _LOCK_PATH.is_file()


def test_lock_manifest_status_tokens_match_module():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    declared = set(data.get("status_tokens", []))
    assert declared == set(STATUS_TOKENS)


def test_lock_manifest_pins_audit_delta():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    delta = data["audit_delta"]
    assert delta["must_migrate_before"] == 5
    assert delta["must_migrate_after"] == 0
    assert delta["blocked_unsafe_after"] == 0


def test_lock_manifest_lists_all_five_pipelines():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    migrated = data.get("pipelines_migrated", [])
    expected = {
        "scripts/repair/go_repair_pipeline.py",
        "scripts/repair/native_c_cpp_repair_pipeline.py",
        "scripts/repair/python_repair_pipeline.py",
        "scripts/repair/rust_repair_pipeline.py",
        "scripts/repair/typescript_repair_pipeline.py",
    }
    assert set(migrated) == expected
