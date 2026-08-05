"""Tests for determinex_io_extractor.py's negative-assertion (NotIn) handling (2026-07-16),
the seventh fix in the skip-rate chain.

Found while sampling codesnap-rs__codesnap (highest remaining skip rate, 64%, after fixes
1-6): `assert "unexpected argument" not in output.lower()` -- a top-level `ast.NotIn`
Compare, the semantic mirror of the already-handled `ast.In`. _resolve_in_snippet's
resolution logic (const, for-loop expansion, f-string-with-variable) is identical regardless
of In vs NotIn -- only which list the caller appends to differs -- so it was generalized to
accept both operators rather than duplicated.

Unlike the OR-groups fix (fix 6), this needed no AND/OR design decision: `not in` is always
a simple universal negation ("this must never appear"), with none of expect_in_any's
ambiguity about which branch holds. Sized precisely before building (top-level NotIn assert
specifically): 77/520 (14.8%) of codesnap's skips. Verified via A/B counterfactual on real
data (never AST-presence counting alone, per the standing lesson from fix 5): +61 examples
recovered (294 -> 355 of 814 tests).
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


# ---------- _resolve_in_snippet(): now generalized to accept NotIn too ----------


def test_resolve_in_snippet_accepts_notin_operator():
    compare = ast.parse('"needle" not in haystack').body[0].value
    items, ci = iox._resolve_in_snippet(compare, {}, {})
    assert items == ["needle"]


def test_resolve_in_snippet_notin_case_insensitive():
    compare = ast.parse('"needle" not in haystack.lower()').body[0].value
    items, ci = iox._resolve_in_snippet(compare, {}, {})
    assert items == ["needle"]
    assert ci


def test_resolve_in_snippet_rejects_other_operators():
    """Only In/NotIn are accepted -- an Eq compare must still return empty."""
    compare = ast.parse("x == y").body[0].value
    items, ci = iox._resolve_in_snippet(compare, {}, {})
    assert items == []


# ---------- _find_expectations(): NotIn routes to expect_not_in, not expect_in ----------


def test_find_expectations_notin_routes_to_not_in_not_contains():
    func = _func(
        "def test_x():\n"
        "    r = run(['x'])\n"
        "    assert 'unexpected argument' not in r.stdout.lower()\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert not_in == ["unexpected argument"]
    assert contains == []
    assert ci


def test_find_expectations_in_and_notin_coexist_correctly():
    """A test with BOTH a positive and negative check on the same output must resolve
    both correctly, not conflate the two lists."""
    func = _func(
        "def test_x():\n"
        "    r = run(['x'])\n"
        "    assert 'ok' in r.stdout\n"
        "    assert 'error' not in r.stdout\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert contains == ["ok"]
    assert not_in == ["error"]


def test_find_expectations_notin_with_tuple_unpacked_variable():
    """Combines correctly with fix 3's local-variable resolution layer."""
    func = _func(
        "def test_x():\n"
        "    code, out = run_exe(['x'])\n"
        "    assert 'unexpected argument' not in out\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    shapes = {"run_exe": {"rc_pos": 0, "stdout_pos": 1}}
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver, wrapper_shapes=shapes
    )
    assert not_in == ["unexpected argument"]


def test_find_expectations_notin_only_test_no_other_signal_still_extractable():
    """A test whose ONLY expectation is a NotIn check must still be recognized as having a
    real signal -- confirms the skip-decision itself was updated, not just resolution."""
    func = _func("def test_x():\n    r = run(['x'])\n    assert 'crash' not in r.stdout\n")
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert not_in == ["crash"]


def test_boolop_or_branch_still_rejects_notin():
    """The BoolOp(Or) handling from fix 6 must remain scoped to In only -- NotIn inside an
    Or was never validated against real data and shouldn't silently start being accepted."""
    func = _func(
        "def test_x():\n    r = run(['x'])\n    assert 'a' not in r.stdout or 'b' in r.stdout\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert in_any == []


# ---------- Example dataclass: the new field ----------


def test_example_has_expect_not_in_field_defaulting_empty():
    ex = iox.Example(test="t")
    assert ex.expect_not_in == []


# ---------- end-to-end: extract_file() recovers the real codesnap pattern ----------


def test_extract_file_recovers_notin_pattern(tmp_path):
    test_file = tmp_path / "test_codesnap.py"
    test_file.write_text(
        "import subprocess\n"
        "def run_command(args):\n"
        "    r = subprocess.run(['codesnap', *args], capture_output=True, text=True)\n"
        "    return r.returncode, r.stdout, r.stderr\n"
        "def get_combined_output(returncode, stdout, stderr):\n"
        "    return stdout + stderr\n"
        "def test_output_short_flag():\n"
        "    returncode, stdout, stderr = run_command(['-o', 'test.png', '-c', 'test'])\n"
        "    output = get_combined_output(returncode, stdout, stderr)\n"
        "    assert 'unexpected argument' not in output.lower()\n"
        "    assert 'required arguments' not in output.lower()\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    assert cov.skipped == []
    ex = cov.examples[0]
    assert sorted(ex.expect_not_in) == ["required arguments", "unexpected argument"]
