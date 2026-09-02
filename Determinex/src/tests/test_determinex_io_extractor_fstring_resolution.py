"""Tests for determinex_io_extractor.py's f-string-with-variable resolution (2026-07-16).

IMPORTANT CONTEXT (read before trusting the sizing numbers anywhere else in this codebase):
the pattern this fixes (`assert f"stat {missing}" in out` where `missing` is a local
variable) was originally sized via a naive AST-presence scan ("does this skipped function
contain an f-string with a variable ANYWHERE") at 96/627 (15.3%) of stgit's skips and
197/791 (24.9%) of lazygit's skips -- both estimates turned out to be FALSE POSITIVES. A
rigorous A/B check (disable this resolver, diff the real extract_dir() output against the
same real corpus data with it enabled) measured the ACTUAL impact on stgit at EXACTLY ZERO
recovered examples: the sampled functions used f-strings in test SETUP code, not inside the
actual checked assertion, and their real skip cause was something else entirely (a
top-level `assert X or Y` BoolOp shape this extractor doesn't handle at all).

This function is still correct and still worth keeping -- it does exactly what it claims on
the shape it targets, verified below -- but its measured real-world hit rate on the two
tools sampled was zero. Lesson: size a new pattern by A/B counterfactual (does REMOVING this
logic actually change the extract_dir() output on real data?), never by "does this AST shape
appear somewhere in a skipped function," which produces false positives whenever the
pattern is incidental (e.g. used in setup/fixture code) rather than the actual skip cause.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_resolves_fstring_with_locally_bound_variable():
    node = ast.parse('f"stat {missing}"').body[0].value
    result = iox._resolve_fstring_with_vars(node, {"missing": "/tmp/foo"})
    assert result == "stat /tmp/foo"


def test_resolves_fstring_with_only_literal_parts():
    node = ast.parse('f"count is {1}"').body[0].value
    result = iox._resolve_fstring_with_vars(node, {})
    assert result == "count is 1"


def test_returns_none_for_unresolvable_variable():
    node = ast.parse('f"stat {missing}"').body[0].value
    assert iox._resolve_fstring_with_vars(node, {}) is None


def test_returns_none_for_non_fstring_node():
    node = ast.parse('"plain string"').body[0].value
    assert iox._resolve_fstring_with_vars(node, {}) is None


def test_returns_none_when_any_part_unresolvable():
    """Never guesses -- if even one interpolated part can't be resolved, the whole
    f-string resolution fails rather than producing a partially-wrong string."""
    node = ast.parse('f"{known} and {unknown}"').body[0].value
    result = iox._resolve_fstring_with_vars(node, {"known": "a"})
    assert result is None


def test_find_expectations_recovers_fstring_in_check():
    func = next(
        n
        for n in ast.walk(
            ast.parse(
                "def test_x():\n"
                '    missing = "/tmp/foo"\n'
                "    p = run_tool(['x'])\n"
                '    assert f"stat {missing}" in p.stdout\n'
            )
        )
        if isinstance(n, ast.FunctionDef)
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert contains == ["stat /tmp/foo"]


def test_find_expectations_does_not_add_none_when_fstring_unresolvable():
    """Regression guard: an unresolvable f-string must not silently become a bogus
    'contains' entry (e.g. the string "None")."""
    func = next(
        n
        for n in ast.walk(
            ast.parse(
                "def test_x():\n"
                "    p = run_tool(['x'])\n"
                '    assert f"stat {some_pytest_fixture}" in p.stdout\n'
            )
        )
        if isinstance(n, ast.FunctionDef)
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert contains == []
