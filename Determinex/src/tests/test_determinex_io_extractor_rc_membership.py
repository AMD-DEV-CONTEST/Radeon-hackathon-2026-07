"""Test for fix 44 (2026-07-17): `assert result.returncode in [0, 1]` -- RC
MEMBERSHIP, a real, common "either success or this specific known failure is
acceptable" claim. Found via calcurse (72 occurrences of this exact top-level
shape). Distinct from expect_rc (exact single value) and expect_rc_nonzero (any
nonzero): the test claims membership in a SPECIFIC small set of literal ints, no
more and no less. Recording expect_rc=0 would be too strict (a correct candidate
returning 1 would wrongly fail an expectation the real test never imposed);
expect_rc_nonzero would be wrong the other way (0 is explicitly allowed).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _get_func(src: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_find_expectations_resolves_rc_in_list():
    func = _get_func(
        """
def test_x():
    result = run()
    assert result.returncode in [0, 1]
""",
        "test_x",
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, rc_nonzero, rc_in = iox._find_expectations(
        func, resolver
    )
    assert rc is None
    assert rc_nonzero is False
    assert rc_in == [0, 1]


def test_find_expectations_rc_in_reversed_operand_order_declines():
    """`0 in [result.returncode]` is not the shape we resolve -- the rc must be the
    LEFT side of the `in`, matching the real idiom (`result.returncode in [...]`)."""
    func = _get_func(
        """
def test_x():
    result = run()
    assert 0 in [result.returncode]
""",
        "test_x",
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, rc_nonzero, rc_in = iox._find_expectations(
        func, resolver
    )
    assert rc_in == []


def test_find_expectations_rc_in_declines_non_int_list():
    func = _get_func(
        """
def test_x():
    result = run()
    assert result.returncode in ["a", "b"]
""",
        "test_x",
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, rc_nonzero, rc_in = iox._find_expectations(
        func, resolver
    )
    assert rc_in == []


def test_find_expectations_rc_in_does_not_leak_into_contains():
    """A plain `x in list_of_strings` check elsewhere in the same function must
    still route through the ordinary string-contains path, unaffected."""
    func = _get_func(
        """
def test_x():
    result = run()
    assert result.returncode in [0, 1]
    assert "ok" in result.stdout
""",
        "test_x",
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, rc_nonzero, rc_in = iox._find_expectations(
        func, resolver
    )
    assert rc_in == [0, 1]
    assert contains == ["ok"]


def test_extract_file_resolves_rc_in_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess

EXECUTABLE = "/workspace/executable"

def run(*args):
    return subprocess.run([EXECUTABLE, *args], capture_output=True)
""",
        encoding="utf-8",
    )
    src = """
from conftest import run

def test_empty_data_directory():
    result = run("-Q", "--read-only")
    assert result.returncode in [0, 1]
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.expect_rc is None
    assert e.expect_rc_nonzero is False
    assert e.expect_rc_in == [0, 1]


def test_local_oracle_check_enforces_rc_in():
    import determinex_local_oracle as oracle

    ex = iox.Example(test="t", expect_rc_in=[0, 1])
    ok, reason, detail = oracle._check(ex, 0, "", "")
    assert ok
    ok, reason, detail = oracle._check(ex, 1, "", "")
    assert ok
    ok, reason, detail = oracle._check(ex, 2, "", "")
    assert not ok
    assert reason == "rc_in"


def test_local_oracle_check_rc_in_empty_list_is_inert():
    """An Example with no rc_in claim (the default empty list) must impose no
    constraint at all -- matches expect_in/expect_not_in's existing behavior for
    an empty list."""
    import determinex_local_oracle as oracle

    ex = iox.Example(test="t")
    ok, reason, detail = oracle._check(ex, 7, "", "")
    assert ok
