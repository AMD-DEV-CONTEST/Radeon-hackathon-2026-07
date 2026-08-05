"""Tests for determinex_io_extractor.py's BoolOp(Or) / OR-group handling (2026-07-16), the
sixth fix in the skip-rate chain -- and the one built with a real schema decision, not a
quick pattern-match patch.

Found while investigating why the (ultimately zero-impact, see
test_determinex_io_extractor_fstring_resolution.py's module docstring) f-string sizing was
a false positive: the real skip cause for the sampled function was `assert A or B` -- a
top-level BoolOp shape _find_expectations didn't handle at all. Precisely sized (top-level
BoolOp specifically, not "BoolOp appears somewhere"): 172/627 (27.4%) of stgit's skips have
this shape -- the largest single bucket found in the whole investigation.

THE KEY DESIGN POINT: `assert A or B` is an OR-semantics claim (at least one branch must
hold). The existing `Example.expect_in` (`contains`) field is AND-semantics (every entry
must be present). Naively flattening both operands into `contains` would incorrectly demand
BOTH -- a genuinely correct reimplementation satisfying only one disjunct would then wrongly
fail an expectation the real test never imposed. `Example.expect_in_any` is a NEW field: a
list of OR-groups, each group a list of alternatives where at least one must be present.
`assert A and B` (a different BoolOp) is exactly equivalent to two separate asserts and
flattens safely into the existing AND-semantics `contains` -- no new field needed there.
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


# ---------- _resolve_in_snippet(): the shared single-comparison resolver ----------


def test_resolve_in_snippet_literal():
    compare = ast.parse('"needle" in haystack').body[0].value
    items, ci = iox._resolve_in_snippet(compare, {}, {})
    assert items == ["needle"]
    assert not ci


def test_resolve_in_snippet_case_insensitive():
    compare = ast.parse('"needle" in haystack.lower()').body[0].value
    items, ci = iox._resolve_in_snippet(compare, {}, {})
    assert items == ["needle"]
    assert ci


def test_resolve_in_snippet_bytes_literal():
    compare = ast.parse('b"needle" in haystack').body[0].value
    items, ci = iox._resolve_in_snippet(compare, {}, {})
    assert items == ["needle"]


def test_resolve_in_snippet_not_an_in_compare_returns_empty():
    compare = ast.parse("x == y").body[0].value
    items, ci = iox._resolve_in_snippet(compare, {}, {})
    assert items == []


def test_resolve_in_snippet_unresolvable_returns_empty():
    compare = ast.parse("some_var in haystack").body[0].value
    items, ci = iox._resolve_in_snippet(compare, {}, {})
    assert items == []


# ---------- BoolOp(Or): the real, sized pattern ----------


def test_find_expectations_or_of_two_in_checks_becomes_one_group():
    func = _func(
        "def test_x():\n"
        "    r = run(['pull'])\n"
        "    assert r.returncode == 0\n"
        "    assert b'squash' in r.stdout.lower() or b'patch' in r.stdout.lower()\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert rc == 0
    assert contains == []
    assert in_any == [["squash", "patch"]]
    assert ci  # picked up from .lower() on either branch


def test_find_expectations_or_of_three_in_checks():
    func = _func(
        "def test_x():\n"
        "    r = run(['x'])\n"
        "    assert 'a' in r.stdout or 'b' in r.stdout or 'c' in r.stdout\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert in_any == [["a", "b", "c"]]


def test_find_expectations_or_with_one_unresolvable_branch_adds_nothing():
    """Never guess a partial OR-group -- if even one branch can't be resolved, the whole
    group is dropped rather than recording a narrower (and possibly wrong) constraint."""
    func = _func(
        "def test_x():\n"
        "    r = run(['x'])\n"
        "    assert some_dynamic_value in r.stdout or 'b' in r.stdout\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert in_any == []
    assert contains == []


def test_find_expectations_or_with_non_in_branch_adds_nothing():
    """A branch that isn't itself a simple `snippet in stream` Compare (e.g. an Eq) means
    the whole OR-group shape wasn't the one this fix targets -- skip it, don't guess."""
    func = _func(
        "def test_x():\n    r = run(['x'])\n    assert r.returncode == 1 or 'b' in r.stdout\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert in_any == []


def test_find_expectations_multiple_or_groups_in_one_function():
    func = _func(
        "def test_x():\n"
        "    r = run(['x'])\n"
        "    assert 'a' in r.stdout or 'b' in r.stdout\n"
        "    assert 'c' in r.stdout or 'd' in r.stdout\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert in_any == [["a", "b"], ["c", "d"]]


# ---------- BoolOp(And): flattens safely into the existing AND-semantics contains ----------


def test_find_expectations_and_of_two_in_checks_flattens_to_contains():
    func = _func(
        "def test_x():\n    r = run(['x'])\n    assert 'a' in r.stdout and 'b' in r.stdout\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert sorted(contains) == ["a", "b"]
    assert in_any == []


# ---------- Example dataclass: the new field ----------


def test_example_has_expect_in_any_field_defaulting_empty():
    ex = iox.Example(test="t")
    assert ex.expect_in_any == []


# ---------- end-to-end: extract_file() recovers the real stgit-shaped pattern ----------


def test_extract_file_recovers_boolop_or_pattern(tmp_path):
    test_file = tmp_path / "test_stgit.py"
    test_file.write_text(
        "import subprocess\n"
        "def run(*args):\n"
        "    return subprocess.run(['stg', *args], capture_output=True)\n"
        "def test_pull_command():\n"
        "    result = run('pull')\n"
        "    assert result.returncode == 0\n"
        "    assert b'squash' in result.stdout.lower() or b'patch' in result.stdout.lower()\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    assert cov.skipped == []
    ex = cov.examples[0]
    assert ex.expect_rc == 0
    assert ex.expect_in_any == [["squash", "patch"]]


def test_extract_file_or_only_test_no_other_signal_still_recovered(tmp_path):
    """A test whose ONLY expectation is the OR-group (no rc/exact/plain-contains) must
    still be extracted -- confirms the skip-check itself was updated, not just the
    resolution logic."""
    test_file = tmp_path / "test_stgit.py"
    test_file.write_text(
        "import subprocess\n"
        "def run(*args):\n"
        "    return subprocess.run(['stg', *args], capture_output=True)\n"
        "def test_x():\n"
        "    result = run('x')\n"
        "    assert 'a' in result.stdout or 'b' in result.stdout\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    assert cov.skipped == []
    assert cov.examples[0].expect_in_any == [["a", "b"]]
