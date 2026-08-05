"""
Tests for scripts/determinex_oracle.py — the Universal Ground-Truth Oracle.

This module had ZERO direct test coverage before 2026-07-02, despite being
the single most load-bearing piece of the system ("the compiler is the
only oracle" — every corpus claim, every training pair, ultimately
traces back to this). Found live during a corpus-center audit: pass/fail
itself was always correct, but total/n_passed were silently dead (always
0/0) on every JUnit-backed oracle (python/jvm/swift/dotnet/ruby/php/
typescript) since the fields were never assigned. Not a correctness bug —
the load-bearing pass/fail guarantee was intact — but a real gap since
determinex_oracle_env's OpenEnv observation contract exposes total/n_passed
to external RL consumers.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


import determinex_oracle as oracle_mod
from determinex_oracle import _junit_counts, _junit_failures, get_oracle

_JUNIT_XML_MIXED = """<?xml version="1.0"?>
<testsuite tests="4" failures="1" errors="1" skipped="1">
  <testcase classname="test_mod" name="test_pass_one" />
  <testcase classname="test_mod" name="test_pass_two" />
  <testcase classname="test_mod" name="test_fails">
    <failure message="assert 1 == 2">AssertionError</failure>
  </testcase>
  <testcase classname="test_mod" name="test_errors">
    <error message="boom">RuntimeError</error>
  </testcase>
  <testcase classname="test_mod" name="test_skipped">
    <skipped message="not applicable" />
  </testcase>
</testsuite>
"""


def test_junit_counts_on_mixed_results(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text(_JUNIT_XML_MIXED, encoding="utf-8")

    total, n_passed = _junit_counts(xml)

    # 5 testcases total: 2 pass, 1 failure, 1 error, 1 skipped.
    assert total == 5
    assert n_passed == 2


def test_junit_failures_on_mixed_results(tmp_path):
    xml = tmp_path / "junit.xml"
    xml.write_text(_JUNIT_XML_MIXED, encoding="utf-8")

    failures = _junit_failures(xml)

    statuses = {f.name: f.status for f in failures}
    assert statuses["test_fails"] == "failure"
    assert statuses["test_errors"] == "failure"  # errors normalize to failure status
    assert statuses["test_skipped"] == "skipped"
    assert "test_pass_one" not in statuses
    assert "test_pass_two" not in statuses


def test_junit_counts_missing_file_returns_zero(tmp_path):
    assert _junit_counts(tmp_path / "does_not_exist.xml") == (0, 0)


def test_junit_counts_malformed_xml_returns_zero(tmp_path):
    xml = tmp_path / "bad.xml"
    xml.write_text("not valid xml <<<", encoding="utf-8")
    assert _junit_counts(xml) == (0, 0)


# ── Live end-to-end: the actual python oracle against real pytest ──────────


def _write_solution(workdir: Path, body: str) -> None:
    (workdir / "solution.py").write_text(body, encoding="utf-8")
    (workdir / "test_solution.py").write_text(
        "from solution import add\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )


def test_python_oracle_live_broken_submission_fails_with_real_traceback(tmp_path):
    _write_solution(tmp_path, "def add(a, b):\n    return a - b\n")  # deliberately wrong

    oracle = get_oracle("python")
    result = oracle.verify(tmp_path)

    assert result.passed is False
    assert result.total == 1
    assert result.n_passed == 0
    assert len(result.failures) == 1
    assert "assert" in result.failures[0].text.lower()


def test_python_oracle_live_fixed_submission_passes(tmp_path):
    _write_solution(tmp_path, "def add(a, b):\n    return a + b\n")

    oracle = get_oracle("python")
    result = oracle.verify(tmp_path)

    assert result.passed is True
    assert result.total == 1
    assert result.n_passed == 1
    assert result.failures == []


def test_python_oracle_never_silently_passes_on_collection_error(tmp_path):
    """A submission that doesn't even import cleanly must never report passed=True."""
    (tmp_path / "test_broken_import.py").write_text(
        "from nonexistent_module import whatever\n", encoding="utf-8"
    )

    oracle = get_oracle("python")
    result = oracle.verify(tmp_path)

    assert result.passed is False


# ---------------------------------------------------------------------------
# Two more "silently lies" bugs found live 2026-07-22 while testing the
# multi-subproject repair pipeline (determinex_ingest.discover_subprojects +
# determinex_repair.repair_workspace_all) end to end against this repo's own
# packages/*/frontend/vscode-extension subprojects:
#
# 1. _verify_typescript reported passed=True whenever tsc/jest failed to
#    even LAUNCH (missing binary, bad --no-install resolution, config
#    error) with a nonzero exit that didn't happen to contain a parseable
#    "error TSxxxx" / JUnit failure line -- `failures` stayed empty, so the
#    oracle claimed "0 errors" when it had never actually run a check.
# 2. _verify_python reported passed=False with EMPTY failures and no
#    explanation whenever pytest exited nonzero for a reason other than a
#    parsed test failure (most commonly: exit code 5, "no tests were
#    collected", for a small package whose tests live elsewhere) -- an
#    unexplained, unactionable "fails for no stated reason".
#
# Both violate this file's own module docstring: "A stub raises
# OracleUnavailable... rather than silently passing -- the oracle never
# lies." Ryan, live: "it should be fixed to where it all compiles and
# reports one way or the other."
# ---------------------------------------------------------------------------


def _cp(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_verify_python_no_tests_collected_is_an_honest_pass(tmp_path):
    """pytest exit code 5 ('no tests were collected') is NOT the same claim
    as 'this package is broken' -- must pass, not fail with 0 explained
    failures."""
    with patch.object(oracle_mod, "_run", return_value=_cp(5, stdout="no tests ran\n")):
        result = oracle_mod._verify_python(tmp_path)
    assert result.passed is True
    assert result.failures == []


def test_verify_python_real_collection_error_is_a_visible_failure(tmp_path):
    """A genuine crash/import error (nonzero exit, NOT code 5, no JUnit
    failures parsed because the run never got that far) must surface as a
    real, readable failure -- not silently 0 failures alongside passed=False."""
    with patch.object(
        oracle_mod,
        "_run",
        return_value=_cp(2, stderr="ImportError: No module named 'determinex_missing_dep'\n"),
    ):
        result = oracle_mod._verify_python(tmp_path)
    assert result.passed is False
    assert len(result.failures) == 1
    assert "ImportError" in result.failures[0].text


def test_verify_typescript_tsc_failed_to_launch_is_not_a_silent_pass(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    with patch.object(
        oracle_mod,
        "_run",
        return_value=_cp(127, stderr="npm ERR! could not determine executable to run\n"),
    ):
        result = oracle_mod._verify_typescript(tmp_path)
    assert result.passed is False
    assert any("tsc exited" in f.text for f in result.failures)


def test_verify_typescript_real_type_errors_still_reported_normally(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    with patch.object(
        oracle_mod,
        "_run",
        return_value=_cp(
            2, stdout="src/index.ts(10,5): error TS2322: Type 'string' is not assignable.\n"
        ),
    ):
        result = oracle_mod._verify_typescript(tmp_path)
    assert result.passed is False
    assert len(result.failures) == 1
    assert "TS2322" in result.failures[0].text


def test_verify_typescript_jest_no_tests_found_is_not_a_failure(tmp_path):
    # Must declare jest -- otherwise _has_test_framework skips the run
    # entirely (see test_verify_typescript_no_test_framework_is_an_honest_pass),
    # which would make this pass for the wrong reason.
    (tmp_path / "package.json").write_text(
        '{"devDependencies": {"jest": "^29.0.0"}}', encoding="utf-8"
    )
    with patch.object(
        oracle_mod, "_run", return_value=_cp(1, stdout="No tests found, exiting with code 1\n")
    ):
        result = oracle_mod._verify_typescript(tmp_path)
    assert result.passed is True


def test_verify_typescript_no_test_framework_does_not_invoke_a_runner_and_does_not_pass(tmp_path):
    """Renamed and its verdict corrected 2026-07-29.

    The original intent is right and is preserved below: this repo's own vscode-extension has a
    package.json with no jest/vitest and no real "test" script, and the oracle must NOT shell out
    to a runner that is not there and then read npx's refusal as a test failure.

    But the original assertion was `passed is True`, and its docstring called that a "vacuous
    pass". That is the one thing this project's doctrine forbids -- "an oracle never silently
    passes" -- and it made the assertion lock in the defect rather than guard against it. Note the
    fixture ships NO tsconfig.json either, so nothing whatsoever was checked; the real extension
    does ship one and still passes on the type check alone.

    Not attempting the runner and not claiming a pass are independent, and both are required.
    """
    (tmp_path / "package.json").write_text(
        '{"scripts": {"compile": "tsc -p ./"}, "devDependencies": {"typescript": "^5.4.0"}}',
        encoding="utf-8",
    )
    with patch.object(oracle_mod, "_run") as mock_run:
        result = oracle_mod._verify_typescript(tmp_path)

    mock_run.assert_not_called()
    assert result.passed is False
    assert result.total == 0
    assert "nothing was verified" in result.failures[0].text


def test_verify_typescript_npm_init_placeholder_test_script_is_not_a_framework(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "echo \\"Error: no test specified\\" && exit 1"}}',
        encoding="utf-8",
    )
    assert oracle_mod._has_test_framework(tmp_path) is False


def test_verify_typescript_jest_failed_to_launch_is_not_a_silent_pass(tmp_path):
    # Must actually declare jest -- a bare {} has no test framework configured
    # at all, which is a DIFFERENT, correct "nothing to verify" pass (see
    # test_verify_typescript_no_test_framework_is_an_honest_pass below).
    (tmp_path / "package.json").write_text(
        '{"devDependencies": {"jest": "^29.0.0"}}', encoding="utf-8"
    )
    with patch.object(
        oracle_mod,
        "_run",
        return_value=_cp(127, stderr="npx: command not found\n"),
    ):
        result = oracle_mod._verify_typescript(tmp_path)
    assert result.passed is False
    assert any("jest exited" in f.text for f in result.failures)


# ---------------------------------------------------------------------------
# vitest support -- found live 2026-07-22: this project's OWN frontend uses
# vitest ("test": "vitest run" in package.json, no jest anywhere), but
# _verify_typescript unconditionally ran jest, which npx (correctly,
# per --no-install) refused to auto-install -- read as a real test failure
# for a project whose real test suite (85 passing tests) was never actually
# invoked.
# ---------------------------------------------------------------------------


def test_uses_vitest_detects_vitest_config_file(tmp_path):
    (tmp_path / "vitest.config.ts").write_text("export default {}\n", encoding="utf-8")
    assert oracle_mod._uses_vitest(tmp_path) is True


def test_uses_vitest_detects_vitest_in_package_json_devdeps(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"devDependencies": {"vitest": "^4.1.7"}}', encoding="utf-8"
    )
    assert oracle_mod._uses_vitest(tmp_path) is True


def test_uses_vitest_false_for_plain_jest_project(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"devDependencies": {"jest": "^29.0.0"}}', encoding="utf-8"
    )
    assert oracle_mod._uses_vitest(tmp_path) is False


def test_verify_typescript_routes_to_vitest_when_detected(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"devDependencies": {"vitest": "^4.1.7"}}', encoding="utf-8"
    )
    captured_cmd = {}

    def _fake_run(cmd, cwd, timeout=600):
        captured_cmd["cmd"] = cmd
        return _cp(0, stdout="ok\n")

    with patch.object(oracle_mod, "_run", side_effect=_fake_run):
        oracle_mod._verify_typescript(tmp_path)
    assert "vitest" in captured_cmd["cmd"]
    assert "jest" not in captured_cmd["cmd"]


# ---------------------------------------------------------------------------
# Oracle pool expansion 2026-07-22 -- Ryan: "i need c, java, kotlin, swift,
# etc oracles... as well as a legacy set of oracles which are cobol, basic,
# etc... there should be a rust pure oracle, and a pure tauri one... there
# should be oracles in this oracle pool that cover all languages and systems
# and programs." java/kotlin/swift already existed (jvm/swift oracles); this
# adds the ones that didn't: c, cpp, cobol, basic, tauri (composite). Same
# "never silently lie" contract as every oracle above: a compiler/build
# system that fails to even launch, with no parsed error line, must surface
# as an explained failure, not an empty-failures pass or fail.
# ---------------------------------------------------------------------------


def test_verify_c_no_build_system_falls_back_to_syntax_only_per_file(tmp_path):
    (tmp_path / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")
    captured_cmd = {}

    def _fake_run(cmd, cwd, timeout=600):
        captured_cmd["cmd"] = cmd
        return _cp(0)

    with patch.object(oracle_mod, "_run", side_effect=_fake_run):
        result = oracle_mod._verify_c(tmp_path)
    assert result.passed is True
    assert captured_cmd["cmd"][0] == "gcc"
    assert "-fsyntax-only" in captured_cmd["cmd"]


def test_verify_c_real_compile_error_is_parsed(tmp_path):
    (tmp_path / "main.c").write_text("int main() { return x; }\n", encoding="utf-8")
    err = "main.c:1:22: error: 'x' undeclared (first use in this function)\n"
    with patch.object(oracle_mod, "_run", return_value=_cp(1, stderr=err)):
        result = oracle_mod._verify_c(tmp_path)
    assert result.passed is False
    assert len(result.failures) == 1
    assert "x" in result.failures[0].text


def test_verify_c_no_sources_is_an_explained_failure_not_a_silent_pass(tmp_path):
    result = oracle_mod._verify_c(tmp_path)
    assert result.passed is False
    assert result.failures[0].text == "no *.c found"


def test_verify_c_launch_failure_with_no_parsed_errors_is_not_a_silent_pass(tmp_path):
    """A compiler that fails to even launch (missing component, bad flags)
    with a nonzero exit and no parseable 'file:line: error' text must never
    read as passed=True/0-failures."""
    (tmp_path / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")
    with patch.object(oracle_mod, "_run", return_value=_cp(127, stderr="gcc: command not found\n")):
        result = oracle_mod._verify_c(tmp_path)
    assert result.passed is False
    assert len(result.failures) == 1
    assert "command not found" in result.failures[0].text


def test_verify_c_prefers_cmake_when_shipped(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("project(x)\n", encoding="utf-8")
    captured_cmds = []

    def _fake_run(cmd, cwd, timeout=600):
        captured_cmds.append(cmd)
        return _cp(0)

    with patch.object(oracle_mod, "_run", side_effect=_fake_run):
        result = oracle_mod._verify_c(tmp_path)
    assert result.passed is True
    assert captured_cmds[0][0] == "cmake"
    assert captured_cmds[1][:2] == ["cmake", "--build"]


def test_verify_cpp_real_compile_error_is_parsed(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() { return x; }\n", encoding="utf-8")
    err = "main.cpp:1:22: error: 'x' was not declared in this scope\n"
    with patch.object(oracle_mod, "_run", return_value=_cp(1, stderr=err)):
        result = oracle_mod._verify_cpp(tmp_path)
    assert result.passed is False
    assert "x" in result.failures[0].text


def test_verify_cobol_compiles_each_source_with_cobc(tmp_path):
    (tmp_path / "hello.cob").write_text(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. HELLO.\n", encoding="utf-8"
    )
    captured_cmd = {}

    def _fake_run(cmd, cwd, timeout=120):
        captured_cmd["cmd"] = cmd
        return _cp(0)

    with patch.object(oracle_mod, "_run", side_effect=_fake_run):
        result = oracle_mod._verify_cobol(tmp_path)
    assert result.passed is True
    assert result.total == 1
    assert captured_cmd["cmd"] == ["cobc", "-c", str(tmp_path / "hello.cob")]


def test_verify_cobol_compile_failure_is_reported_per_file(tmp_path):
    (tmp_path / "broken.cob").write_text("NOT VALID COBOL\n", encoding="utf-8")
    with patch.object(oracle_mod, "_run", return_value=_cp(1, stderr="broken.cob: syntax error\n")):
        result = oracle_mod._verify_cobol(tmp_path)
    assert result.passed is False
    assert len(result.failures) == 1


def test_verify_cobol_no_sources_is_an_explained_failure(tmp_path):
    result = oracle_mod._verify_cobol(tmp_path)
    assert result.passed is False
    assert "no .cob/.cbl" in result.failures[0].text


def test_verify_basic_compiles_each_source_with_fbc(tmp_path):
    (tmp_path / "hello.bas").write_text('PRINT "hello"\n', encoding="utf-8")
    captured_cmd = {}

    def _fake_run(cmd, cwd, timeout=120):
        captured_cmd["cmd"] = cmd
        return _cp(0)

    with patch.object(oracle_mod, "_run", side_effect=_fake_run):
        result = oracle_mod._verify_basic(tmp_path)
    assert result.passed is True
    assert captured_cmd["cmd"] == ["fbc", "-c", str(tmp_path / "hello.bas")]


def test_verify_basic_no_sources_is_an_explained_failure(tmp_path):
    result = oracle_mod._verify_basic(tmp_path)
    assert result.passed is False
    assert "no .bas" in result.failures[0].text


def test_verify_tauri_requires_a_real_tauri_layout(tmp_path):
    """A directory with no src-tauri/ (or Cargo.toml+tauri.conf.json) is not
    a Tauri project -- must fail with an explanation, not silently attempt
    a cargo build against a nonexistent path."""
    result = oracle_mod._verify_tauri(tmp_path)
    assert result.passed is False
    assert "not a Tauri project" in result.failures[0].text


def test_verify_tauri_passes_only_when_both_backend_and_frontend_pass(tmp_path):
    src_tauri = tmp_path / "src-tauri"
    src_tauri.mkdir()
    (src_tauri / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    (src_tauri / "tauri.conf.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    with (
        patch.object(
            oracle_mod,
            "_verify_rust",
            return_value=oracle_mod.OracleResult(passed=True, oracle="rust"),
        ),
        patch.object(
            oracle_mod,
            "_verify_typescript",
            return_value=oracle_mod.OracleResult(passed=True, oracle="typescript"),
        ),
    ):
        result = oracle_mod._verify_tauri(tmp_path)
    assert result.passed is True


def test_verify_tauri_fails_if_frontend_fails_even_when_backend_passes(tmp_path):
    """The whole point of the composite oracle: a passing cargo check next
    to a broken frontend build is NOT a real pass for the app."""
    src_tauri = tmp_path / "src-tauri"
    src_tauri.mkdir()
    (src_tauri / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    (src_tauri / "tauri.conf.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    frontend_fail = oracle_mod.OracleResult(
        passed=False,
        oracle="typescript",
        failures=[oracle_mod.Failure("tsc", "typecheck", "error TS2322", status="failure")],
    )
    with (
        patch.object(
            oracle_mod,
            "_verify_rust",
            return_value=oracle_mod.OracleResult(passed=True, oracle="rust"),
        ),
        patch.object(oracle_mod, "_verify_typescript", return_value=frontend_fail),
    ):
        result = oracle_mod._verify_tauri(tmp_path)
    assert result.passed is False
    assert len(result.failures) == 1


# ---------------------------------------------------------------------------
# System/database oracles added 2026-07-22 -- Ryan: "duckdb/mongodb/mariadb
# all of it should be there... all languages, all systems, all programs."
# duckdb is embedded (no server); mariadb/mongodb are Docker-backed ephemeral
# (a native Windows service install for MariaDB was tried live and failed/
# rolled back with a generic MSI 1603 -- exactly the fragile, elevation-
# hungry path an ephemeral verification sandbox shouldn't depend on).
# ---------------------------------------------------------------------------


def test_verify_duckdb_no_sources_is_an_explained_failure(tmp_path):
    result = oracle_mod._verify_duckdb(tmp_path)
    assert result.passed is False
    assert "no .sql found" in result.failures[0].text


def test_verify_duckdb_passes_when_no_error_lines_and_zero_exit(tmp_path):
    (tmp_path / "schema.sql").write_text("CREATE TABLE t(x INT);\n", encoding="utf-8")
    with patch.object(oracle_mod, "_run", return_value=_cp(0, stdout="")):
        result = oracle_mod._verify_duckdb(tmp_path)
    assert result.passed is True
    assert result.total == 1


def test_verify_duckdb_catches_error_lines_even_with_bail_off_semantics(tmp_path):
    """The CLI (sqlite3-style) keeps going after a failed statement and can
    still exit 0 -- a parsed 'Error:' line must fail the oracle regardless
    of the process exit code, or a real broken script would silently pass."""
    (tmp_path / "bad.sql").write_text("SELEC 1;\n", encoding="utf-8")
    with patch.object(
        oracle_mod, "_run", return_value=_cp(0, stdout="Error: Parser Error: syntax error\n")
    ):
        result = oracle_mod._verify_duckdb(tmp_path)
    assert result.passed is False
    assert len(result.failures) == 1


def test_verify_duckdb_uses_bail_on_and_read_dot_commands(tmp_path):
    sql = tmp_path / "x.sql"
    sql.write_text("SELECT 1;\n", encoding="utf-8")
    captured = {}

    def _fake_run(cmd, cwd, timeout=120):
        captured["cmd"] = cmd
        return _cp(0)

    with patch.object(oracle_mod, "_run", side_effect=_fake_run):
        oracle_mod._verify_duckdb(tmp_path)
    assert ".bail on" in captured["cmd"]
    assert any(sql.as_posix() in c for c in captured["cmd"] if ".read" in c)


def test_verify_mariadb_no_sources_is_an_explained_failure(tmp_path):
    result = oracle_mod._verify_mariadb(tmp_path)
    assert result.passed is False
    assert "no .sql found" in result.failures[0].text


def test_verify_mariadb_docker_start_failure_is_explained(tmp_path):
    (tmp_path / "seed.sql").write_text("SELECT 1;\n", encoding="utf-8")
    with patch.object(
        oracle_mod,
        "_docker",
        return_value=_cp(1, stderr="docker: Cannot connect to the Docker daemon\n"),
    ):
        result = oracle_mod._verify_mariadb(tmp_path)
    assert result.passed is False
    assert "docker-start" in result.failures[0].name


def test_verify_mariadb_startup_timeout_is_explained_not_a_silent_pass(tmp_path):
    (tmp_path / "seed.sql").write_text("SELECT 1;\n", encoding="utf-8")

    def _fake_docker(cmd, timeout=300):
        if cmd[:2] == ["docker", "run"]:
            return _cp(0, stdout="containerid\n")
        return _cp(1, stderr="not ready\n")  # every readiness probe fails

    with (
        patch.object(oracle_mod, "_docker", side_effect=_fake_docker),
        patch.object(oracle_mod, "_wait_for_container_ready", return_value=False),
    ):
        result = oracle_mod._verify_mariadb(tmp_path)
    assert result.passed is False
    assert "never became ready" in result.failures[0].text


def test_verify_mariadb_runs_each_sql_file_and_tears_down_container(tmp_path):
    (tmp_path / "seed.sql").write_text("SELECT 1;\n", encoding="utf-8")
    calls = []

    def _fake_docker(cmd, timeout=300):
        calls.append(cmd)
        return _cp(0, stdout="ok\n")

    with (
        patch.object(oracle_mod, "_docker", side_effect=_fake_docker),
        patch.object(oracle_mod, "_wait_for_container_ready", return_value=True),
    ):
        result = oracle_mod._verify_mariadb(tmp_path)
    assert result.passed is True
    assert any(c[:2] == ["docker", "run"] for c in calls)
    assert any(c[:2] == ["docker", "rm"] for c in calls)  # always torn down


# ---------------------------------------------------------------------------
# Live 2026-07-23: the official mariadb:11 image's entrypoint runs a
# TEMPORARY bootstrap mysqld first (binds the port, answers ping) purely to
# apply MARIADB_ROOT_PASSWORD, then stops it and starts the REAL server
# ~10-15s later (confirmed via `docker logs`: two "ready for connections"
# lines with "Temporary server stopped" between them). A readiness probe
# landing in that temporary-server window reports ready, but the first real
# exec right after can get a genuine `ERROR 1045 Access denied` with the
# CORRECT password -- a startup race, not a bad credential. Reproduced live
# against a real container before this fix existed.
# ---------------------------------------------------------------------------


def test_run_with_transient_retry_retries_on_access_denied_then_succeeds(tmp_path):
    calls = []

    def _fake_docker(cmd, timeout=300):
        calls.append(cmd)
        if len(calls) < 3:
            return _cp(1, stderr="ERROR 1045 (28000): Access denied for user 'root'@'localhost'\n")
        return _cp(0, stdout="ok\n")

    with patch.object(oracle_mod, "_docker", side_effect=_fake_docker):
        result = oracle_mod._run_with_transient_retry(["docker", "exec", "x"], timeout=60, delay=0)
    assert result.returncode == 0
    assert len(calls) == 3


def test_run_with_transient_retry_does_not_mask_a_real_sql_error(tmp_path):
    """A genuine syntax error must NOT be retried away -- only the specific
    transient-auth signature triggers a retry."""
    calls = []

    def _fake_docker(cmd, timeout=300):
        calls.append(cmd)
        return _cp(1, stderr="ERROR 1064 (42000): You have an error in your SQL syntax\n")

    with patch.object(oracle_mod, "_docker", side_effect=_fake_docker):
        result = oracle_mod._run_with_transient_retry(["docker", "exec", "x"], timeout=60, delay=0)
    assert result.returncode == 1
    assert len(calls) == 1  # no retry -- this isn't the transient signature


def test_run_with_transient_retry_gives_up_after_max_attempts(tmp_path):
    calls = []

    def _fake_docker(cmd, timeout=300):
        calls.append(cmd)
        return _cp(1, stderr="ERROR 1045 (28000): Access denied for user 'root'@'localhost'\n")

    with patch.object(oracle_mod, "_docker", side_effect=_fake_docker):
        result = oracle_mod._run_with_transient_retry(
            ["docker", "exec", "x"], timeout=60, attempts=3, delay=0
        )
    assert result.returncode == 1
    assert len(calls) == 3


def test_verify_mongodb_no_sources_is_an_explained_failure(tmp_path):
    result = oracle_mod._verify_mongodb(tmp_path)
    assert result.passed is False
    assert "no .js found" in result.failures[0].text


def test_verify_mongodb_runs_each_script_and_tears_down_container(tmp_path):
    (tmp_path / "seed.js").write_text("db.x.insertOne({a:1});\n", encoding="utf-8")
    calls = []

    def _fake_docker(cmd, timeout=300):
        calls.append(cmd)
        return _cp(0, stdout="ok\n")

    with (
        patch.object(oracle_mod, "_docker", side_effect=_fake_docker),
        patch.object(oracle_mod, "_wait_for_container_ready", return_value=True),
    ):
        result = oracle_mod._verify_mongodb(tmp_path)
    assert result.passed is True
    assert any(c[:2] == ["docker", "run"] for c in calls)
    assert any(c[:2] == ["docker", "rm"] for c in calls)


def test_typescript_oracle_refuses_a_workspace_with_nothing_to_verify(tmp_path):
    """An oracle never silently passes -- including when it did nothing.

    `_verify_typescript` ran the type check only when tsconfig.json existed and tests only when
    package.json declared a test script, then set `passed = len(failures) == 0`. With neither
    present nothing ran, no failures were recorded, and it returned passed=True with total=0.
    The explanation was appended to `.raw`, which no caller inspects.

    This is the Python `compileall`-over-zero-files bug relocated into the universal registry:
    every other oracle in this module already refuses an empty tree. It compounds because
    verified_search turns a generation exception into the candidate string
    "__generation_error__: ..." and verifies it like any other candidate, so against a lenient
    oracle that string comes back solved with a proof line attached.
    """
    result = oracle_mod._verify_typescript(tmp_path)
    assert result.passed is False
    assert result.failures, "must record why nothing could be verified"
    assert "nothing was verified" in result.failures[0].text


def test_typescript_oracle_refuses_broken_source_that_ships_no_config(tmp_path):
    """The damaging shape: real code, genuinely wrong, and no config to check it with."""
    (tmp_path / "bad.ts").write_text('const a: number = "not a number";\n', encoding="utf-8")

    result = oracle_mod._verify_typescript(tmp_path)

    assert result.passed is False, (
        "a workspace containing a type error must not pass merely because it shipped no tsconfig"
    )


def test_verify_mongodb_script_failure_is_reported(tmp_path):
    (tmp_path / "bad.js").write_text("throw new Error('boom');\n", encoding="utf-8")

    def _fake_docker(cmd, timeout=300):
        if cmd[:2] == ["docker", "run"]:
            return _cp(0, stdout="containerid\n")
        if "mongosh" in cmd and "--eval" not in cmd:
            return _cp(1, stderr="Uncaught Error: boom\n")
        return _cp(0)

    with (
        patch.object(oracle_mod, "_docker", side_effect=_fake_docker),
        patch.object(oracle_mod, "_wait_for_container_ready", return_value=True),
    ):
        result = oracle_mod._verify_mongodb(tmp_path)
    assert result.passed is False
    assert len(result.failures) == 1
