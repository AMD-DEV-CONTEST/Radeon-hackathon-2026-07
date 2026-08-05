"""Tests for determinex_io_extractor.py's strip-wrapped stdout comparison handling
(2026-07-16), the fourth fix in the skip-rate chain.

Found by sampling `ariga__atlas` (a real ProgramBench tool with a high remaining skip count
after fixes 1-3): `p.stdout.strip() == "expected"` is a very common shape (158 skipped tests
in this ONE tool alone) that `_is_out_expr` couldn't see -- it only recognized a bare
attribute/role-name, not a `.strip()`/`.rstrip()`/`.lstrip()` call wrapping it.

Important semantic point this fix is careful about: `X.strip() == "expected"` is a WEAKER
claim than `X == "expected"` -- the real test tolerates whatever surrounding whitespace the
real binary produces. Recording it as an EXACT match would make the extracted expectation
STRICTER than what the test actually verifies (a correct reimplementation that emits a
trailing newline would then wrongly fail an expectation the real test never imposed). So a
stripped comparison is routed into `contains`, never `exact`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402

# ---------- _is_out_expr_maybe_stripped(): detection + stripped flag ----------


def test_detects_strip_wrapped_attribute():
    node = ast.parse("p.stdout.strip()").body[0].value
    is_out, stripped = iox._is_out_expr_maybe_stripped(node, {})
    assert is_out
    assert stripped


def test_detects_rstrip_wrapped_attribute():
    node = ast.parse("p.stdout.rstrip()").body[0].value
    is_out, stripped = iox._is_out_expr_maybe_stripped(node, {})
    assert is_out
    assert stripped


def test_detects_lstrip_wrapped_attribute():
    node = ast.parse("p.stdout.lstrip()").body[0].value
    is_out, stripped = iox._is_out_expr_maybe_stripped(node, {})
    assert is_out
    assert stripped


def test_bare_attribute_not_flagged_as_stripped():
    node = ast.parse("p.stdout").body[0].value
    is_out, stripped = iox._is_out_expr_maybe_stripped(node, {})
    assert is_out
    assert not stripped


def test_detects_strip_wrapped_role_name():
    node = ast.parse("out.strip()").body[0].value
    is_out, stripped = iox._is_out_expr_maybe_stripped(node, {"out": "stdout"})
    assert is_out
    assert stripped


def test_unrelated_strip_call_not_flagged_as_out():
    node = ast.parse("some_string.strip()").body[0].value
    is_out, stripped = iox._is_out_expr_maybe_stripped(node, {})
    assert not is_out


def test_unrelated_method_call_not_flagged():
    """Only strip/rstrip/lstrip should be peeled -- not an arbitrary method call."""
    node = ast.parse("p.stdout.upper()").body[0].value
    is_out, stripped = iox._is_out_expr_maybe_stripped(node, {})
    assert not is_out


# ---------- _find_expectations(): stripped comparisons route to contains, not exact ----------


def test_find_expectations_strip_wrapped_routes_to_contains_not_exact():
    """THE regression guard for the semantic point: a stripped comparison must never
    become `exact` -- that would over-constrain the reimplementation."""
    func = next(
        n
        for n in ast.walk(
            ast.parse(
                "def test_x():\n"
                "    p = run_tool(['--help'])\n"
                '    assert p.stdout.strip() == "expected output"\n'
            )
        )
        if isinstance(n, ast.FunctionDef)
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert exact is None
    assert contains == ["expected output"]


def test_find_expectations_bare_comparison_still_routes_to_exact():
    """Regression guard the other direction: a NON-stripped comparison must still produce
    an exact match, unchanged from before this fix."""
    func = next(
        n
        for n in ast.walk(
            ast.parse(
                "def test_x():\n"
                "    p = run_tool(['--help'])\n"
                '    assert p.stdout == "expected output"\n'
            )
        )
        if isinstance(n, ast.FunctionDef)
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert exact == "expected output"
    assert contains == []


def test_find_expectations_strip_wrapped_on_right_hand_side():
    func = next(
        n
        for n in ast.walk(
            ast.parse(
                "def test_x():\n"
                "    p = run_tool(['--help'])\n"
                '    assert "expected output" == p.stdout.strip()\n'
            )
        )
        if isinstance(n, ast.FunctionDef)
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert exact is None
    assert contains == ["expected output"]


def test_find_expectations_strip_wrapped_role_name_via_tuple_unpack():
    """Combines with the local-variable resolution layer: a tuple-unpacked `out` variable,
    then `.strip()`'d before comparison."""
    func = next(
        n
        for n in ast.walk(
            ast.parse(
                "def test_x():\n"
                "    code, out = run_exe(['-h'])\n"
                '    assert out.strip() == "expected"\n'
            )
        )
        if isinstance(n, ast.FunctionDef)
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    shapes = {"run_exe": {"rc_pos": 0, "stdout_pos": 1}}
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver, wrapper_shapes=shapes
    )
    assert exact is None
    assert contains == ["expected"]


def test_find_expectations_empty_stripped_value_not_appended():
    """A stripped comparison against an empty string shouldn't add a useless empty-string
    'contains' entry (which would trivially match anything)."""
    func = next(
        n
        for n in ast.walk(
            ast.parse(
                "def test_x():\n    p = run_tool(['--help'])\n    assert p.stdout.strip() == \"\"\n"
            )
        )
        if isinstance(n, ast.FunctionDef)
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert exact is None
    assert contains == []


# ---------- end-to-end: extract_file() recovers the real atlas pattern ----------


def test_extract_file_recovers_strip_wrapped_comparison(tmp_path):
    test_file = tmp_path / "test_atlas.py"
    test_file.write_text(
        "import subprocess\n"
        "def run_atlas(args):\n"
        "    return subprocess.run(['atlas', *args], capture_output=True, text=True)\n"
        "def test_schema_fmt_prints_path():\n"
        "    p = run_atlas(['schema', 'fmt', 'x.hcl'])\n"
        "    assert p.returncode == 0\n"
        '    assert p.stdout.strip() == "/abs/path/x.hcl"\n',
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    assert cov.skipped == []
    ex = cov.examples[0]
    assert ex.expect_rc == 0
    assert ex.expect_stdout is None
    assert ex.expect_in == ["/abs/path/x.hcl"]
