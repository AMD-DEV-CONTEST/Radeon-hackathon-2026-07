"""Tests for determinex_io_extractor.py's @pytest.mark.parametrize expansion (2026-07-16),
the eighth fix in the skip-rate chain.

Found while sampling blacknon__hwatch (highest remaining skip rate among a fresh 6-tool
scan after fixes 1-7): parametrized flag-variant suites like

    @pytest.mark.parametrize("flag", ["-b", "--batch"])
    def test_batch_flag(self, flag):
        stdout, stderr, returncode = run_command([flag, "echo", "test"])
        assert "test" in clean_stdout or "test" in stderr

never resolved, because the bare `Name` node for `flag` inside the argv list literal has
no entry in vars_map -- pytest supplies the concrete value per collected test item, not
via any assignment `_track_vars` can see. `_resolve()` already looks up `Name.id` in
vars_map for any other bare variable, so the fix is purely in supplying the substitution:
detect a single-name, constant-list `@pytest.mark.parametrize`, and run the SAME
extraction pipeline once per concrete value with `{argname: value}` injected into
vars_map, producing one Example per case (test name suffixed `[value]`, matching pytest's
own per-item naming idiom).

`n_tests` now increments once per parametrized CASE, not once per FunctionDef -- this
also fixes a latent accuracy bug in the skip-rate denominator itself (a parametrized test
was previously undercounted as a single test regardless of how many items pytest actually
collects), independent of any new examples recovered.

Sized via real A/B counterfactual on real HuggingFace corpus data (never AST-presence
counting alone, per the standing lesson from fix 5): on hwatch's test_arg_parsing.py alone,
109->124 tests (accurate denominator), 71->93 examples (+22 recovered). Across a fresh
6-tool sample (atlas/ov/xh/hwatch/codesnap/lazygit, 3 branches each): hwatch +22 examples,
codesnap +7, lazygit +12, xh +2 (xh's remaining skips are mostly blocked by the separate
http_server dynamic-port network-fixture issue, not this one).

Scope is deliberately narrow, matching the "never guess" discipline of prior fixes:
single parametrize argname only (no "a,b" multi-param strings), values must each be a
plain constant (str/int/float/bool) -- anything else falls back to the pre-existing skip
behavior rather than guessing.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _func(src: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))


# ---------- _parametrize_cases() ----------


def test_parametrize_cases_simple_string_list():
    node = _func("""
@pytest.mark.parametrize("flag", ["-b", "--batch"])
def test_x(flag):
    pass
""")
    cases = iox._parametrize_cases(node)
    assert cases == [{"flag": "-b"}, {"flag": "--batch"}]


def test_parametrize_cases_int_values():
    node = _func("""
@pytest.mark.parametrize("n", [0, 1, 5])
def test_x(n):
    pass
""")
    cases = iox._parametrize_cases(node)
    assert cases == [{"n": 0}, {"n": 1}, {"n": 5}]


def test_parametrize_cases_tuple_literal():
    node = _func("""
@pytest.mark.parametrize("flag", ("-b", "--batch"))
def test_x(flag):
    pass
""")
    cases = iox._parametrize_cases(node)
    assert cases == [{"flag": "-b"}, {"flag": "--batch"}]


def test_parametrize_cases_no_decorator_returns_none():
    node = _func("""
def test_x():
    pass
""")
    assert iox._parametrize_cases(node) is None


def test_parametrize_cases_multi_param_name_bails():
    """ "a,b" multi-arg parametrize is out of scope -- never guess at splitting it."""
    node = _func("""
@pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])
def test_x(a, b):
    pass
""")
    assert iox._parametrize_cases(node) is None


def test_parametrize_cases_non_constant_values_bail():
    node = _func("""
@pytest.mark.parametrize("flag", [some_dynamic_list])
def test_x(flag):
    pass
""")
    assert iox._parametrize_cases(node) is None


def test_parametrize_cases_mixed_decorators_are_ignored():
    """A non-parametrize decorator alongside a real one shouldn't confuse detection."""
    node = _func("""
@pytest.mark.timeout(5)
@pytest.mark.parametrize("flag", ["-b", "--batch"])
def test_x(flag):
    pass
""")
    cases = iox._parametrize_cases(node)
    assert cases == [{"flag": "-b"}, {"flag": "--batch"}]


def test_parametrize_cases_stacked_decorators_cartesian_product():
    node = _func("""
@pytest.mark.parametrize("a", [1, 2])
@pytest.mark.parametrize("b", ["x", "y"])
def test_x(a, b):
    pass
""")
    cases = iox._parametrize_cases(node)
    assert len(cases) == 4
    assert {"a": 1, "b": "x"} in cases
    assert {"a": 2, "b": "y"} in cases


def test_parametrize_cases_empty_list_returns_none():
    node = _func("""
@pytest.mark.parametrize("flag", [])
def test_x(flag):
    pass
""")
    assert iox._parametrize_cases(node) is None


# ---------- extract_file() integration ----------


def test_extract_file_expands_parametrized_flag_into_two_examples(tmp_path):
    src = """
import subprocess

EXECUTABLE = "./executable"

def run_command(args):
    r = subprocess.run([EXECUTABLE] + args, capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode

@pytest.mark.parametrize("flag", ["-b", "--batch"])
def test_batch_flag(flag):
    stdout, stderr, returncode = run_command([flag, "echo", "test"])
    assert "test" in stdout or "test" in stderr
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_tests == 2
    assert cov.n_examples == 2
    names = {e.test for e in cov.examples}
    assert names == {"test_batch_flag[-b]", "test_batch_flag[--batch]"}
    by_name = {e.test: e for e in cov.examples}
    # "executable" now correctly prepended (fix 34, 2026-07-17): run_command's
    # subprocess.run() call is assigned to `r` then returned via `r.stdout, ...`
    # (not a direct `return subprocess.run(...)`) -- previously invisible to base
    # learning entirely, so the executable placeholder silently went missing.
    assert by_name["test_batch_flag[-b]"].argv == ["executable", "-b", "echo", "test"]
    assert by_name["test_batch_flag[--batch]"].argv == ["executable", "--batch", "echo", "test"]
    assert by_name["test_batch_flag[-b]"].expect_in_any == [["test", "test"]]


def test_extract_file_non_parametrized_test_unaffected(tmp_path):
    """A plain (non-parametrized) test still produces exactly one example, one test name,
    with no [..] suffix -- the fix must not disturb the existing common case."""
    src = """
import subprocess

EXECUTABLE = "./executable"

def run_command(args):
    r = subprocess.run([EXECUTABLE] + args, capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode

def test_version():
    stdout, stderr, returncode = run_command(["--version"])
    assert returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_tests == 1
    assert cov.n_examples == 1
    assert cov.examples[0].test == "test_version"
    # "executable" now correctly prepended (fix 34, 2026-07-17) -- see the sibling
    # test_extract_file_expands_parametrized_flag_into_two_examples comment.
    assert cov.examples[0].argv == ["executable", "--version"]


def test_extract_file_parametrize_with_unresolvable_values_falls_back_to_one_skip(tmp_path):
    """A parametrize whose values can't be resolved must not silently drop coverage --
    it should fall back to treating the function as ONE unparametrized (and therefore
    unresolvable-argv) test, matching pre-fix behavior exactly."""
    src = """
import subprocess

EXECUTABLE = "./executable"

def run_command(args):
    r = subprocess.run([EXECUTABLE] + args, capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode

@pytest.mark.parametrize("flag", [some_dynamic_list])
def test_batch_flag(flag):
    stdout, stderr, returncode = run_command([flag, "echo", "test"])
    assert "test" in stdout or "test" in stderr
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_tests == 1
    assert cov.n_examples == 0
    assert cov.skipped == ["test_batch_flag"]
