"""Tests for determinex_io_extractor.py's custom assertion-helper resolution (2026-07-16).

Same principle as wrapper-name auto-discovery (see test_determinex_io_extractor_wrapper_
discovery.py), applied to the OTHER half of a test: many real suites factor repeated
assertion shapes into a helper (`assert_err(proc, rc, substrings)`) instead of inlining
`assert proc.returncode == rc` + a loop of `assert s in proc.stderr`.
_find_expectations only recognized inline ast.Compare assertions -- invisible to it entirely.

Two real bugs were caught by validating against real jq test source before trusting this,
not just synthetic cases:
  1. jq's real assert_err decodes stderr to a local variable (`err = proc.stderr.decode(...)`)
     before looping -- a direct-attribute-only check missed it; fixed via _stream_attr's local
     variable tracking.
  2. A custom assertion helper is called as a BARE EXPRESSION STATEMENT (`assert_err(proc, 2,
     [...])`), not wrapped in an outer `assert` keyword -- the helper does its own internal
     asserting. The first implementation only walked ast.Assert nodes and silently missed
     every real call site until this was caught against real data.
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


# ---------- _stream_attr(): direct attribute vs .decode() wrapped vs unrelated ----------


def test_stream_attr_direct_attribute():
    node = ast.parse("proc.stderr").body[0].value
    assert iox._stream_attr(node) == "stderr"


def test_stream_attr_decode_wrapped():
    node = ast.parse('proc.stdout.decode("utf-8", errors="replace")').body[0].value
    assert iox._stream_attr(node) == "stdout"


def test_stream_attr_unrelated_attribute_returns_none():
    node = ast.parse("proc.returncode").body[0].value
    assert iox._stream_attr(node) is None


def test_stream_attr_unrelated_call_returns_none():
    node = ast.parse("proc.strip()").body[0].value
    assert iox._stream_attr(node) is None


# ---------- _analyze_assertion_helper(): role mapping, including local-var indirection ----------


def test_analyze_assertion_helper_direct_attribute_shape():
    helper = _func(
        "def assert_err(proc, rc, substrings):\n"
        "    assert proc.returncode == rc\n"
        "    for s in substrings:\n"
        "        assert s in proc.stderr\n"
    )
    mapping = iox._analyze_assertion_helper(helper)
    assert mapping["rc_param"] == "rc"
    assert mapping["contains_param"] == "substrings"
    assert mapping["_params"] == ["proc", "rc", "substrings"]


def test_analyze_assertion_helper_local_variable_indirection_shape():
    """The REAL jq shape: stderr decoded to a local var before the loop."""
    helper = _func(
        "def assert_err(proc, rc, substrings):\n"
        "    assert proc.returncode == rc\n"
        '    err = proc.stderr.decode("utf-8", errors="replace")\n'
        "    for s in substrings:\n"
        "        assert s in err\n"
    )
    mapping = iox._analyze_assertion_helper(helper)
    assert mapping["rc_param"] == "rc"
    assert mapping["contains_param"] == "substrings"


def test_analyze_assertion_helper_unrelated_function_returns_empty():
    helper = _func("def add(a, b):\n    return a + b\n")
    assert iox._analyze_assertion_helper(helper) == {}


def test_analyze_assertion_helper_rc_only_still_recorded():
    """A helper that only checks rc (no substring loop) should still register rc_param."""
    helper = _func("def assert_rc(proc, expected):\n    assert proc.returncode == expected\n")
    mapping = iox._analyze_assertion_helper(helper)
    assert mapping["rc_param"] == "expected"
    assert "contains_param" not in mapping


# ---------- _discover_assertion_helpers(): own file + sibling helper module ----------


def test_discover_assertion_helpers_finds_locally_defined_helper():
    src = (
        "def assert_err(proc, rc, substrings):\n"
        "    assert proc.returncode == rc\n"
        "    for s in substrings:\n"
        "        assert s in proc.stderr\n"
        "def test_x():\n"
        "    assert_err(proc, 2, ['bad flag'])\n"
    )
    tree = ast.parse(src)
    helpers = iox._discover_assertion_helpers(tree, Path("test_fake.py"))
    assert "assert_err" in helpers


def test_discover_assertion_helpers_finds_sibling_conftest_helper(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "def assert_err(proc, rc, substrings):\n"
        "    assert proc.returncode == rc\n"
        "    for s in substrings:\n"
        "        assert s in proc.stderr\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_thing.py"
    test_file.write_text("def test_it():\n    pass\n", encoding="utf-8")
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    helpers = iox._discover_assertion_helpers(tree, test_file)
    assert "assert_err" in helpers


# ---------- _resolve_assertion_helper_call(): resolves the CALL SITE's actual arguments ----------


def test_resolve_assertion_helper_call_extracts_rc_and_contains():
    mapping = {
        "rc_param": "rc",
        "contains_param": "substrings",
        "_params": ["proc", "rc", "substrings"],
    }
    call = ast.parse('assert_err(proc, 2, ["Unknown option -z", "Use jq --help"])').body[0].value
    rc, contains = iox._resolve_assertion_helper_call(call, mapping)
    assert rc == 2
    assert contains == ["Unknown option -z", "Use jq --help"]


def test_resolve_assertion_helper_call_missing_rc_param_returns_none():
    mapping = {"contains_param": "substrings", "_params": ["proc", "substrings"]}
    call = ast.parse('assert_err(proc, ["a"])').body[0].value
    rc, contains = iox._resolve_assertion_helper_call(call, mapping)
    assert rc is None
    assert contains == ["a"]


# ---------- _find_expectations(): the actual bug -- bare expression statement ----------


def test_find_expectations_recognizes_bare_expression_statement_call():
    """THE regression guard for the real bug: assert_err(proc, 2, [...]) is a bare ast.Expr
    statement, not wrapped in `assert` -- the first implementation only walked ast.Assert
    nodes and silently missed every real call site until caught against real jq data."""
    func = _func(
        "def test_unknown_flag():\n"
        "    proc = run_jq(['-z'])\n"
        "    assert_err(proc, 2, ['Unknown option -z', 'Use jq --help'])\n"
    )
    helpers = {
        "assert_err": {
            "rc_param": "rc",
            "contains_param": "substrings",
            "_params": ["proc", "rc", "substrings"],
        }
    }
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver, helpers
    )
    assert rc == 2
    assert contains == ["Unknown option -z", "Use jq --help"]


def test_find_expectations_also_handles_assert_wrapped_helper_call():
    """The less common shape (assert helper(...)) should also still work."""
    func = _func(
        "def test_unknown_flag():\n"
        "    proc = run_jq(['-z'])\n"
        "    assert assert_err(proc, 2, ['bad flag'])\n"
    )
    helpers = {
        "assert_err": {
            "rc_param": "rc",
            "contains_param": "substrings",
            "_params": ["proc", "rc", "substrings"],
        }
    }
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver, helpers
    )
    assert rc == 2
    assert contains == ["bad flag"]


def test_find_expectations_without_helpers_ignores_unknown_call():
    """Without assertion_helpers, a bare call statement is correctly ignored (not mistaken
    for an inline assertion)."""
    func = _func(
        "def test_x():\n    proc = run_jq(['-z'])\n    assert_err(proc, 2, ['bad flag'])\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert rc is None
    assert contains == []


def test_find_expectations_still_handles_inline_assertions_unchanged():
    """Regression guard: adding assertion-helper support must not disturb the existing
    inline-assertion path."""
    func = _func(
        "def test_x():\n"
        "    r = run(['--help'])\n"
        "    assert r.returncode == 0\n"
        "    assert 'usage' in r.stdout\n"
    )
    resolver = iox._PathResolver(Path("test_fake.py"))
    rc, exact, contains, ci, in_any, not_in, _rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert rc == 0
    assert contains == ["usage"]


# ---------- end-to-end: extract_file() recovers a previously-unresolvable test ----------


def test_extract_file_recovers_assert_err_pattern(tmp_path):
    test_file = tmp_path / "test_mytool.py"
    test_file.write_text(
        "import subprocess\n"
        "def run_jq(args, stdin_bytes=b''):\n"
        "    return subprocess.run(['jq', *args], input=stdin_bytes, capture_output=True)\n"
        "def assert_err(proc, rc, substrings):\n"
        "    assert proc.returncode == rc\n"
        '    err = proc.stderr.decode("utf-8", errors="replace")\n'
        "    for s in substrings:\n"
        "        assert s in err\n"
        "def test_unknown_short_option_errors_with_rc_2():\n"
        "    proc = run_jq(['-z'], stdin_bytes=b'')\n"
        "    assert_err(proc, 2, ['Unknown option -z', 'Use jq --help'])\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    assert cov.skipped == []
    ex = cov.examples[0]
    assert ex.argv == ["-z"]
    assert ex.expect_rc == 2
    assert ex.expect_in == ["Unknown option -z", "Use jq --help"]


def test_extract_file_assert_err_pattern_via_sibling_conftest(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "import subprocess\n"
        "def run_jq(args):\n"
        "    return subprocess.run(['jq', *args], capture_output=True)\n"
        "def assert_err(proc, rc, substrings):\n"
        "    assert proc.returncode == rc\n"
        "    for s in substrings:\n"
        "        assert s in proc.stderr\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_mytool.py"
    test_file.write_text(
        "from conftest import run_jq, assert_err\n"
        "def test_bad_flag():\n"
        "    proc = run_jq(['--nope'])\n"
        "    assert_err(proc, 2, ['unknown flag'])\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    assert cov.skipped == []
