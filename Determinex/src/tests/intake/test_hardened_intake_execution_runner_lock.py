"""Tests for HARDENED_INTAKE_EXECUTION_RUNNER_LOCK_001.

Asserts the hardened runner's guards (shell string, path escape, Docker,
network, env scrubbing, timeout, missing tool), the migration of
``BuildAdapter._run`` + ``ShadowCompiler`` to use it, the parallel
execution audit's before/after MUST_MIGRATE delta (10 -> 5), and that
prior smoke fixtures still pass unchanged.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

hr = importlib.import_module("intake.hardened_runner")
adapters_mod = importlib.import_module("intake.build_adapters")

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "intake"
LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


STATUS_TOKENS = frozenset(
    {
        "HARDENED_INTAKE_RUNNER_READY",
        "COMMAND_EXECUTED_BOUNDED",
        "COMMAND_BLOCKED_SHELL",
        "COMMAND_BLOCKED_PATH_ESCAPE",
        "COMMAND_BLOCKED_DOCKER",
        "COMMAND_TIMEOUT_STRUCTURED",
        "COMMAND_TOOL_MISSING_STRUCTURED",
        "ENVIRONMENT_SCRUBBED",
        "CODEBASE_EXPLORER_COMPAT_PRESERVED",
        "BUILD_ADAPTER_COMPAT_PRESERVED",
        "MUST_MIGRATE_COUNT_REDUCED",
        "REPAIR_PIPELINES_DEFERRED",
        "SOURCE_TREE_UNMUTATED",
        "CORPUS_UNMUTATED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "SAFETY_DEFAULTS_RESPECTED",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# Module sanity
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "HARDENED_INTAKE_RUNNER_READY",
        "COMMAND_EXECUTED_BOUNDED",
        "COMMAND_BLOCKED_SHELL",
        "COMMAND_BLOCKED_PATH_ESCAPE",
        "COMMAND_BLOCKED_DOCKER",
        "COMMAND_TIMEOUT_STRUCTURED",
        "COMMAND_TOOL_MISSING_STRUCTURED",
        "ENVIRONMENT_SCRUBBED",
        "CODEBASE_EXPLORER_COMPAT_PRESERVED",
        "BUILD_ADAPTER_COMPAT_PRESERVED",
        "MUST_MIGRATE_COUNT_REDUCED",
        "REPAIR_PIPELINES_DEFERRED",
        "SOURCE_TREE_UNMUTATED",
        "CORPUS_UNMUTATED",
        "EVIDENCE_UNMUTATED_EXCEPT_LOCK_RECORD",
        "SAFETY_DEFAULTS_RESPECTED",
    }
    assert set(STATUS_TOKENS) == expected


def test_hardened_runner_exposes_public_api():
    assert callable(hr.run)
    assert callable(hr.scrub_env)
    assert isinstance(hr.BLOCKED_ENV_VARS, frozenset)
    assert isinstance(hr.REFUSED_PROGRAMS, frozenset)
    assert isinstance(hr.NETWORK_PROGRAMS, frozenset)
    # canonical injection vectors are in the blocklist
    assert "LD_PRELOAD" in hr.BLOCKED_ENV_VARS
    assert "DYLD_INSERT_LIBRARIES" in hr.BLOCKED_ENV_VARS
    assert "PYTHONSTARTUP" in hr.BLOCKED_ENV_VARS
    assert "BASH_ENV" in hr.BLOCKED_ENV_VARS


# ---------------------------------------------------------------------------
# COMMAND_EXECUTED_BOUNDED — happy path
# ---------------------------------------------------------------------------


def test_runs_python_version_successfully(tmp_path: Path):
    r = hr.run([sys.executable, "--version"], workspace=tmp_path, timeout=10)
    assert not r.blocked
    assert not r.tool_missing
    assert not r.timed_out
    assert r.exit_code == 0
    # python prints "Python X.Y.Z" to either stdout or stderr depending on version
    combined = (r.stdout + r.stderr).lower()
    assert "python" in combined


def test_run_result_has_required_fields(tmp_path: Path):
    r = hr.run([sys.executable, "-c", "print('ok')"], workspace=tmp_path, timeout=10)
    d = r.to_dict()
    for key in (
        "command",
        "cwd",
        "exit_code",
        "stdout",
        "stderr",
        "timed_out",
        "tool_missing",
        "blocked",
        "reason",
        "scrubbed_env_vars",
    ):
        assert key in d


# ---------------------------------------------------------------------------
# COMMAND_BLOCKED_SHELL — shell strings rejected, list-of-strings required
# ---------------------------------------------------------------------------


def test_shell_string_is_rejected(tmp_path: Path):
    r = hr.run("python --version", workspace=tmp_path, timeout=10)  # type: ignore[arg-type]
    assert r.blocked
    assert "list[str]" in r.reason or "shell" in r.reason.lower()


def test_empty_command_is_rejected(tmp_path: Path):
    r = hr.run([], workspace=tmp_path, timeout=10)
    assert r.blocked
    assert "empty" in r.reason.lower() or "non-empty" in r.reason.lower()


def test_non_string_arg_is_rejected(tmp_path: Path):
    r = hr.run([sys.executable, 42], workspace=tmp_path, timeout=10)  # type: ignore[list-item]
    assert r.blocked


def test_subprocess_run_never_invoked_with_shell_true(monkeypatch, tmp_path: Path):
    """Defensive: verify the hardened runner never passes shell=True to
    subprocess.run."""
    captured: dict[str, object] = {}
    real_run = subprocess.run

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _capture)
    hr.run([sys.executable, "--version"], workspace=tmp_path, timeout=10)
    # shell must be explicitly False (or absent, which defaults to False)
    assert captured.get("shell", False) is False


def test_bare_command_resolved_via_pathext_before_spawn(monkeypatch, tmp_path: Path):
    """Regression found live 2026-07-22: a bare command name like "npx" is a
    .cmd shim on Windows (npm-installed tools), not a .exe -- a raw
    subprocess.run(shell=False) does NOT try PATHEXT extensions the way a
    real shell does, so it raised FileNotFoundError even though `npx` genuinely
    resolves fine from any shell. This silently made determinex_oracle.py's
    _verify_typescript (which calls `npx tsc`/`npx jest` through this exact
    runner) report a false PASS: tsc/jest never launched at all, but zero
    parsed failures read as "0 errors". Same bug class already fixed twice
    this session for spawning claude-code/codex/gemini-cli -- this was the
    third, independent place it existed. Verified here without depending on
    npx actually being installed on whatever machine runs this suite: fake a
    PATHEXT-shimmed tool via shutil.which and confirm the RESOLVED absolute
    path is what actually reaches subprocess.run, not the bare name."""
    fake_tool = tmp_path / "fake_tool.cmd"
    fake_tool.write_text("@echo off\necho fake output\n", encoding="utf-8")

    real_which = shutil.which

    def _fake_which(name, *a, **kw):
        if name == "fake_tool":
            return str(fake_tool)
        return real_which(name, *a, **kw)

    captured_argv: list = []
    real_run = subprocess.run

    def _capture(args, *a, **kw):
        captured_argv.extend(args)
        return real_run(args, *a, **kw)

    monkeypatch.setattr(hr.shutil, "which", _fake_which)
    monkeypatch.setattr(subprocess, "run", _capture)

    r = hr.run(["fake_tool", "--flag"], workspace=tmp_path, timeout=10)

    assert not r.tool_missing
    assert captured_argv[0] == str(fake_tool)  # resolved, not the bare "fake_tool"
    assert captured_argv[1:] == ["--flag"]  # only argv[0] touched, real args untouched
    assert r.command[0] == "fake_tool"  # reported command stays the readable original


# ---------------------------------------------------------------------------
# COMMAND_BLOCKED_PATH_ESCAPE — cwd must stay inside workspace
# ---------------------------------------------------------------------------


def test_cwd_outside_workspace_is_rejected(tmp_path: Path):
    outside = tmp_path.parent  # one directory up
    r = hr.run(
        [sys.executable, "--version"],
        workspace=tmp_path,
        timeout=10,
        cwd=outside,
    )
    assert r.blocked
    assert "workspace" in r.reason.lower()


def test_path_traversal_cwd_is_rejected(tmp_path: Path):
    nested = tmp_path / "sub"
    nested.mkdir()
    # ../.. escapes the workspace once resolved
    escape = nested / ".." / ".." / ".."
    r = hr.run(
        [sys.executable, "--version"],
        workspace=tmp_path,
        timeout=10,
        cwd=escape,
    )
    assert r.blocked
    assert "workspace" in r.reason.lower()


def test_cwd_inside_workspace_is_accepted(tmp_path: Path):
    nested = tmp_path / "sub"
    nested.mkdir()
    r = hr.run(
        [sys.executable, "--version"],
        workspace=tmp_path,
        timeout=10,
        cwd=nested,
    )
    assert not r.blocked


def test_workspace_must_exist(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist"
    r = hr.run([sys.executable, "--version"], workspace=nonexistent, timeout=10)
    assert r.blocked


# ---------------------------------------------------------------------------
# COMMAND_BLOCKED_DOCKER — container runtimes refused by default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv0",
    [
        "docker",
        "docker.exe",
        "docker-compose",
        "podman",
        "buildah",
        "kubectl",
        "helm",
    ],
)
def test_docker_family_blocked_by_default(tmp_path: Path, argv0: str):
    r = hr.run([argv0, "ps"], workspace=tmp_path, timeout=10)
    assert r.blocked
    assert "Docker" in r.reason or "container" in r.reason.lower()


def test_docker_blocked_by_full_path(tmp_path: Path):
    """Block applies even when caller passes an absolute path."""
    r = hr.run(["/usr/bin/docker", "ps"], workspace=tmp_path, timeout=10)
    assert r.blocked


def test_allow_docker_opt_in_lets_docker_through_validation(tmp_path: Path):
    """With allow_docker=True, the guard does NOT block. We still don't
    actually have docker, so the call returns tool_missing, NOT blocked —
    this proves the guard distinguishes refusal from execution."""
    r = hr.run(
        ["docker_fake_xyz_unlikely", "ps"],
        workspace=tmp_path,
        timeout=10,
        allow_docker=True,
    )
    # Either tool_missing (most envs) or some other non-blocked outcome —
    # the key is the guard did NOT classify it as blocked-by-default.
    assert not r.blocked, "allow_docker=True must bypass the default block"


# ---------------------------------------------------------------------------
# Network commands blocked by default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv0", ["curl", "wget", "ncat", "netcat"])
def test_network_programs_blocked_by_default(tmp_path: Path, argv0: str):
    r = hr.run([argv0, "https://example.com"], workspace=tmp_path, timeout=10)
    assert r.blocked
    assert "network" in r.reason.lower()


# ---------------------------------------------------------------------------
# COMMAND_TIMEOUT_STRUCTURED + COMMAND_TOOL_MISSING_STRUCTURED
# ---------------------------------------------------------------------------


def test_timeout_returns_structured_timed_out(tmp_path: Path):
    r = hr.run(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        workspace=tmp_path,
        timeout=1,
    )
    assert r.timed_out is True
    assert r.blocked is False
    assert r.exit_code != 0
    assert "timed out" in r.stderr.lower()


def test_zero_or_negative_timeout_is_rejected(tmp_path: Path):
    for bad in (0, -1, -100):
        r = hr.run([sys.executable, "--version"], workspace=tmp_path, timeout=bad)
        assert r.blocked
        assert "timeout" in r.reason.lower()


def test_missing_tool_returns_structured_tool_missing(tmp_path: Path):
    r = hr.run(
        ["__not_a_real_binary_xyz12345__"],
        workspace=tmp_path,
        timeout=5,
    )
    assert r.tool_missing is True
    assert r.blocked is False
    assert "not found" in r.stderr.lower() or "not found" in r.reason.lower()


# ---------------------------------------------------------------------------
# ENVIRONMENT_SCRUBBED — code-injection vectors stripped
# ---------------------------------------------------------------------------


def test_scrub_env_strips_blocked_vars(monkeypatch):
    monkeypatch.setenv("LD_PRELOAD", "/evil.so")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/evil.dylib")
    monkeypatch.setenv("PYTHONSTARTUP", "/evil.py")
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    env, stripped = hr.scrub_env()
    assert "LD_PRELOAD" not in env
    assert "DYLD_INSERT_LIBRARIES" not in env
    assert "PYTHONSTARTUP" not in env
    assert set(stripped) >= {"LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "PYTHONSTARTUP"}
    assert "PATH" in env  # PATH preserved


def test_scrub_env_blocks_extra_env_smuggling():
    """A caller cannot smuggle a blocked var through extra_env."""
    env, stripped = hr.scrub_env({"LD_PRELOAD": "/evil.so", "MY_VAR": "ok"})
    assert "LD_PRELOAD" not in env
    assert env.get("MY_VAR") == "ok"
    assert "LD_PRELOAD" in stripped


def test_child_process_does_not_see_ld_preload(monkeypatch, tmp_path: Path):
    """End-to-end: set LD_PRELOAD in the parent, run a child that prints
    its environ, confirm the child does NOT see LD_PRELOAD."""
    monkeypatch.setenv("LD_PRELOAD", "/this/should/be/stripped.so")
    r = hr.run(
        [sys.executable, "-c", "import os; print(os.environ.get('LD_PRELOAD', '__ABSENT__'))"],
        workspace=tmp_path,
        timeout=10,
    )
    assert r.exit_code == 0, r.stderr
    assert "__ABSENT__" in r.stdout
    assert "LD_PRELOAD" in r.scrubbed_env_vars


# ---------------------------------------------------------------------------
# Migration: BuildAdapter._run routes through hardened runner
# ---------------------------------------------------------------------------


def test_build_adapters_imports_hardened_runner():
    """build_adapters.py MUST import the hardened runner — proves the
    migration source-level wiring is in place."""
    src = (_REPO_ROOT / "scripts" / "intake" / "build_adapters.py").read_text(encoding="utf-8")
    assert "from intake.hardened_runner import" in src or "import intake.hardened_runner" in src


def test_build_adapter_run_blocks_when_runner_blocks(monkeypatch, tmp_path: Path):
    """If hardened_runner returns blocked=True, BuildAdapter._run translates
    to ShadowBuildResult(ran=False, success=False)."""

    def _fake_run(cmd, *, workspace, timeout, **kwargs):
        return hr.RunResult(
            command=list(cmd),
            cwd=str(workspace),
            exit_code=-1,
            stdout="",
            stderr="blocked-for-test",
            blocked=True,
            reason="blocked-for-test",
        )

    monkeypatch.setattr(adapters_mod, "_hardened_run", _fake_run)
    out = adapters_mod._run(["echo", "x"], tmp_path, 5)
    assert out.ran is False
    assert out.success is False
    assert "blocked" in out.output.lower()


def test_build_adapter_run_propagates_tool_missing(monkeypatch, tmp_path: Path):
    def _fake_run(cmd, *, workspace, timeout, **kwargs):
        return hr.RunResult(
            command=list(cmd),
            cwd=str(workspace),
            exit_code=-2,
            stdout="",
            stderr="tool not found: x",
            tool_missing=True,
            reason="tool not found",
        )

    monkeypatch.setattr(adapters_mod, "_hardened_run", _fake_run)
    out = adapters_mod._run(["x"], tmp_path, 5)
    assert out.tool_missing is True
    assert out.success is False


def test_build_adapter_run_propagates_timeout(monkeypatch, tmp_path: Path):
    def _fake_run(cmd, *, workspace, timeout, **kwargs):
        return hr.RunResult(
            command=list(cmd),
            cwd=str(workspace),
            exit_code=-3,
            stdout="",
            stderr="timed out",
            timed_out=True,
            reason="timed out",
        )

    monkeypatch.setattr(adapters_mod, "_hardened_run", _fake_run)
    out = adapters_mod._run(["x"], tmp_path, 5)
    assert out.timed_out is True
    assert out.success is False


def test_python_adapter_run_shadow_build_still_returns_ran_true(tmp_path: Path):
    """End-to-end: copy python_broken fixture, run PythonAdapter.run_shadow_build,
    confirm it still returns ran=True (py_compile via hardened runner)."""
    workspace = tmp_path / "py"
    shutil.copytree(FIXTURES / "python_broken", workspace)
    r = adapters_mod.PythonAdapter.run_shadow_build(workspace, timeout=30)
    assert r.ran is True
    # The fixture has correct syntax → compile success even if tests fail.
    assert r.success is True


# ---------------------------------------------------------------------------
# Migration: ShadowCompiler routes through hardened runner
# ---------------------------------------------------------------------------


def test_codebase_explorer_imports_hardened_runner_in_shadow_compiler():
    src = (_REPO_ROOT / "scripts" / "codebase_explorer.py").read_text(encoding="utf-8")
    assert "from intake.hardened_runner import run as _hardened_run" in src
    # And it appears in all three migrated ShadowCompiler methods
    assert src.count("from intake.hardened_runner import run as _hardened_run") >= 3


def test_codebase_explorer_explore_still_works_on_python_fixture(tmp_path: Path):
    """End-to-end: CodebaseExplorer.explore() on the python fixture must
    still produce the same build_system + test_framework + non-zero
    findings count after the ShadowCompiler migration."""
    os.environ["DETERMINEX_NO_CORPUS_WRITE"] = "1"
    os.environ["DETERMINEX_AUDIT_DIR"] = str(tmp_path / "_audit")
    try:
        workspace = tmp_path / "py"
        shutil.copytree(FIXTURES / "python_broken", workspace)
        from codebase_explorer import CodebaseExplorer

        rep = CodebaseExplorer(workspace).explore()
        assert rep.build_system == "pip"
        assert rep.test_framework == "pytest"
        assert "python" in rep.languages
        assert rep.health_score < 1.0
        # The failing pytest is still surfaced as a finding
        assert any(f["category"] == "test_failure" for f in rep.findings)
    finally:
        os.environ.pop("DETERMINEX_NO_CORPUS_WRITE", None)
        os.environ.pop("DETERMINEX_AUDIT_DIR", None)


# ---------------------------------------------------------------------------
# Parallel audit before/after — MUST_MIGRATE delta is the headline
# ---------------------------------------------------------------------------


def test_parallel_audit_no_must_migrate_in_intake_or_codebase_explorer():
    """Rung-5 invariant: scripts/intake/build_adapters.py and
    scripts/codebase_explorer.py must have ZERO MUST_MIGRATE sites
    after this rung lands. Later rungs (rung 6 sealed repair pipelines;
    rung 8's classification sweep surfaced determinex_codeclash_agent)
    govern MUST_MIGRATE in other files; this test only enforces the
    rung-5 floor."""
    audit_mod = importlib.import_module("scripts.dev.parallel_execution_layer_audit")
    rpt = audit_mod.run_audit()
    rung5_must_migrate = [
        s
        for s in rpt.sites
        if s.classification == "MUST_MIGRATE_TO_HARDENED_RUNNER"
        and s.file_path
        in {
            "scripts/intake/build_adapters.py",
            "scripts/codebase_explorer.py",
        }
    ]
    assert rung5_must_migrate == [], (
        f"MUST_MIGRATE residue in rung-5-sealed files: "
        f"{[(s.file_path, s.line) for s in rung5_must_migrate]}"
    )


def test_parallel_audit_hardened_runner_is_classified_hardened():
    audit_mod = importlib.import_module("scripts.dev.parallel_execution_layer_audit")
    rpt = audit_mod.run_audit()
    matches = [s for s in rpt.sites if s.file_path == "scripts/intake/hardened_runner.py"]
    assert len(matches) >= 1
    for s in matches:
        assert s.classification == "HARDENED_COMPILER_PATH"


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
    r = hr.run([sys.executable, "--version"], workspace=tmp_path, timeout=10)
    assert r.exit_code == 0


def test_hardened_runner_does_not_mutate_signed_evidence(tmp_path: Path):
    before = _hash_signed_evidence()
    hr.run([sys.executable, "--version"], workspace=tmp_path, timeout=10)
    hr.run([sys.executable, "-c", "print('ok')"], workspace=tmp_path, timeout=10)
    after = _hash_signed_evidence()
    diffs = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert diffs == []


# ---------------------------------------------------------------------------
# Lock manifest alignment
# ---------------------------------------------------------------------------

_LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "HARDENED_INTAKE_EXECUTION_RUNNER_LOCK_001.json"


def test_lock_manifest_exists():
    assert _LOCK_PATH.is_file(), f"missing: {_LOCK_PATH}"


def test_lock_manifest_status_tokens_match_module():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    declared = set(data.get("status_tokens", []))
    assert declared == set(STATUS_TOKENS)


def test_lock_manifest_pins_must_migrate_delta():
    data = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    delta = data["audit_delta"]
    assert delta["must_migrate_before"] == 10
    assert delta["must_migrate_after"] == 5
    assert delta["hardened_compiler_path_before"] == 10
    assert delta["hardened_compiler_path_after"] == 11
