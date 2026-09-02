"""Tests for determinex_io_extractor.py's run-invoking-fixture fallback (2026-07-16), the
ninth fix in the skip-rate chain -- and the extra_vars extension to _find_expectations that
was needed to fully realize it for parametrized tests.

Found while continuing the tool-by-tool skip-rate audit onto lazygit (56.2% skip after
fix 8) -- a single file, test_help_output.py, had 45/47 tests skipped:

    @pytest.fixture(scope="session")
    def help_long():
        return run_cmd(["--help"])

    def test_help_exit_code_zero(help_long):
        assert help_long.returncode == 0

_find_run_call(test_node, ...) walks the TEST's own body looking for a run-call -- there
isn't one, it's hoisted into the fixture to avoid re-invoking the executable for every
assertion. _is_result_rc/_is_result_out already match on attribute name alone
(`.returncode`/`.stdout`) regardless of how the base name was bound, so the expectation
side needed NO change for the common case -- only argv resolution was missing. Fix:
_track_run_fixtures() finds @pytest.fixture functions whose OWN body is a resolvable
run-call (reusing _find_run_call itself -- it doesn't care whether the FunctionDef it's
given is a test or a fixture), and any test naming exactly ONE such fixture as a parameter
uses that fixture's (argv, stdin, env, files) as a fallback when the test's own body has
none. Two-or-more fixture params (comparing help_long vs help_short) is a different shape
(comparing TWO invocations) this Example model can't express -- correctly left unresolved,
never guessed.

Real A/B counterfactual on lazygit's test_help_output.py: 2->13 examples with JUST the
fixture fallback. A further real gap surfaced: `test_help_documents_flag_tokens(help_long,
flag): assert flag in out` combines the fixture AND a parametrize value referenced directly
in the assertion -- _find_expectations was called ONCE per function, before the parametrize
case loop, so it had no way to know which concrete flag value applied to which case. Fixed
by giving _find_expectations an `extra_vars` parameter (merged into its internal vars_map)
and moving its call inside the per-case loop in extract_file(), and by teaching
_resolve_in_snippet to resolve a bare Name via vars_map (not just loop_vars/f-strings).
Final measured result on the same file: 2->40 examples (of 47 tests) -- skip rate
95.7%->14.9%, with every remaining skip a genuinely different, correctly-unresolvable shape
(generator expressions, re.search, a non-empty check, the two-fixture comparison). Across
the full 6-tool re-scan (3 branches each): lazygit 27->77 examples (89 tests), skip rate
56.2%->13.5%. Other tools unchanged (pattern not present in their sampled branches).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _tree(src: str) -> ast.Module:
    return ast.parse(src)


# ---------- _track_run_fixtures() ----------


def test_track_run_fixtures_finds_a_simple_return_run_call():
    tree = _tree("""
import subprocess

def run_cmd(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

@pytest.fixture(scope="session")
def help_long():
    return run_cmd(["--help"])
""")
    fx = iox._track_run_fixtures(tree, set())
    assert "help_long" in fx
    argv, stdin, env, files = fx["help_long"]
    assert argv == ["--help"]


def test_track_run_fixtures_ignores_non_fixture_functions():
    tree = _tree("""
import subprocess

def run_cmd(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

def help_long():
    return run_cmd(["--help"])
""")
    fx = iox._track_run_fixtures(tree, set())
    assert fx == {}


def test_track_run_fixtures_ignores_fixtures_with_no_run_call():
    tree = _tree("""
@pytest.fixture
def sample_text():
    return "hello world"
""")
    fx = iox._track_run_fixtures(tree, set())
    assert fx == {}


def test_track_run_fixtures_handles_bare_fixture_decorator_name():
    tree = _tree("""
import subprocess
from pytest import fixture

def run_cmd(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

@fixture(scope="session")
def help_short():
    return run_cmd(["-h"])
""")
    fx = iox._track_run_fixtures(tree, set())
    assert "help_short" in fx
    assert fx["help_short"][0] == ["-h"]


# ---------- extract_file() integration: fixture fallback ----------

_HELPER_PREFIX = """
import subprocess

EXECUTABLE = "./executable"

def run_cmd(args):
    return subprocess.run([EXECUTABLE] + args, capture_output=True, text=True)

@pytest.fixture(scope="session")
def help_long():
    return run_cmd(["--help"])

@pytest.fixture(scope="session")
def help_short():
    return run_cmd(["-h"])
"""


def test_extract_file_resolves_test_via_single_fixture_param(tmp_path):
    src = (
        _HELPER_PREFIX
        + """
def test_help_exit_code_zero(help_long):
    assert help_long.returncode == 0
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.test == "test_help_exit_code_zero"
    # "executable" now correctly prepended (fix 32, 2026-07-17): EXECUTABLE = "./executable"
    # is a bare string constant matching the placeholder's basename convention, now
    # recognized by is_exec_ref -- previously silently missing (base failed to resolve
    # at all, so run_cmd's own list argument was treated as the WHOLE argv).
    assert e.argv == ["executable", "--help"]
    assert e.expect_rc == 0


def test_extract_file_two_fixture_params_correctly_unresolved(tmp_path):
    """Comparing two DIFFERENT invocations (help_long vs help_short) is a shape this
    Example model can't express -- must stay skipped, never guess which one is 'the' argv."""
    src = (
        _HELPER_PREFIX
        + """
def test_help_and_h_match(help_long, help_short):
    assert help_long.stdout == help_short.stdout
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 0
    assert cov.skipped == ["test_help_and_h_match"]


def test_extract_file_test_with_own_run_call_ignores_fixture_fallback(tmp_path):
    """A test that already resolves argv from its OWN body must use that, not silently
    prefer a same-named fixture (there is none here, but confirms the fallback only
    engages when the test's own resolution genuinely fails)."""
    src = (
        _HELPER_PREFIX
        + """
def test_version(help_long):
    result = run_cmd(["--version"])
    assert result.returncode == 0
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    # "executable" now correctly prepended (fix 32, 2026-07-17) -- see the sibling
    # test_extract_file_resolves_test_via_single_fixture_param comment.
    assert cov.examples[0].argv == ["executable", "--version"]


# ---------- extract_file() integration: extra_vars (parametrize used in assertion) ----------


def test_extract_file_parametrize_value_used_directly_in_assertion(tmp_path):
    src = (
        _HELPER_PREFIX
        + """
@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_documents_flag_tokens(help_long, flag):
    out = help_long.stdout
    assert flag in out
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_tests == 2
    assert cov.n_examples == 2
    by_name = {e.test: e for e in cov.examples}
    assert by_name["test_help_documents_flag_tokens[-h]"].expect_in == ["-h"]
    assert by_name["test_help_documents_flag_tokens[--help]"].expect_in == ["--help"]
    # both cases share the same fixture-derived argv -- "executable" now correctly
    # prepended (fix 32, 2026-07-17), see test_extract_file_resolves_test_via_single_fixture_param.
    assert by_name["test_help_documents_flag_tokens[-h]"].argv == ["executable", "--help"]


def test_find_expectations_extra_vars_resolves_bare_name_in_check():
    node = next(
        n
        for n in ast.walk(
            ast.parse("""
def test_x(flag):
    assert flag in out
""")
        )
        if isinstance(n, ast.FunctionDef)
    )
    resolver = iox._PathResolver(Path("test_x.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        node, resolver, extra_vars={"flag": "--help"}
    )
    assert contains == ["--help"]


def test_find_expectations_without_extra_vars_leaves_bare_name_unresolved():
    """No extra_vars supplied (the pre-fix call shape) -- must stay conservative, not guess."""
    node = next(
        n
        for n in ast.walk(
            ast.parse("""
def test_x(flag):
    assert flag in out
""")
        )
        if isinstance(n, ast.FunctionDef)
    )
    resolver = iox._PathResolver(Path("test_x.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        node, resolver
    )
    assert contains == []
