"""Tests for the fifteenth/sixteenth/seventeenth fixes in the skip-rate chain (2026-07-17),
built immediately after fix 14 once explicitly told "unfixable isn't a thing... keep finding
and building": sampling the top-4 remaining-skip tools after fix 14 (quickjs, gomplate,
bedtools2, esubaalew__run) found gomplate/bedtools2/run ALL share `cmd = [str(EXECUTABLE)] +
args` -- a base-prefix-list-CONCATENATION shape, not duckdb's flat `cmd = [str(executable),
temp_db]` list -- plus two further real bugs caught only by hand-checking output, not the
aggregate recovery count:

Fix 15 (base+args BinOp-Add shape + positional-list base-loss guard):
  (a) `_extract_wrapper_base_argv` only matched `cmd = [...]` (a plain List assignment);
      extended to also match `cmd = [...] + args` (BinOp Add of a List and the wrapper's
      own variadic-args Name parameter), resolving just the List side as the base.
  (b) The executable placeholder itself is sometimes MODULE-level (`EXECUTABLE = Path(...)
      / "executable"` at the top of conftest.py), one scope further out than duckdb's
      function-local `executable = ...` -- `_discover_wrapper_kwarg_flags` now collects
      module-level assignments per tree and passes them through as `outer_path_exprs`.
  (c) A POSITIONAL list argument (bedtools2's `run_bedtools(args, ...)` has no default,
      so the call is always `run_bedtools([...], cwd=...)`) resolves and short-circuits
      _find_run_call's positional loop BEFORE base could ever be consulted -- the exact
      same silent-base-loss bug fix 14 fixed for the args= KEYWORD path, just via the
      positional path. Fixed by computing is_learned_wrapper/this_base BEFORE the
      positional loop and prepending base whenever a positional List/list resolves.
  (d) The costliest bug: when a positional List literal FAILS to resolve (one element
      unresolvable, e.g. a real on-disk file path -- see fix 16), the original code did
      `continue` and fell through to the this_base-only fallback, silently producing
      argv=['executable'] with EVERY real argument dropped -- confidently wrong, not
      skipped. Caught via esubaalew__run's test_file_execution_simple: the aggregate
      recovery count went UP when this bug was present (a wrong-but-"resolved" example
      counts the same as a right one), only hand-inspecting the actual argv revealed it.
      Fixed with an `unresolvable_list_seen` guard that aborts the candidate entirely.

Fix 16 (RESOURCES-path-as-CLI-arg file staging):
  The bug in 15(d) was caused by `str(RESOURCES / "simple.sh")` as a positional list
  element -- a REAL on-disk file referenced directly by path expression, not a
  write_text-staged local variable (_file_arg/_track_files's existing case). Added
  `_PathResolver.resolve_file_arg` (reads the real file from disk via the same
  eval_path() used for golden-file expectations) and threaded a `resolver` parameter
  through _file_arg -> _resolve_list -> _find_run_call -> extract_file/_track_run_fixtures.

Fix 17 (expect_rc_nonzero):
  `assert result.returncode != 0` ("must fail") was completely unhandled -- rc != 0 has
  no existing field to record it in, and bedtools2's whole test_sortandnaming_* family
  (accounting for the majority of its remaining skips after fixes 15+16) is exactly this
  shape. Added Example.expect_rc_nonzero (bool) + a NotEq branch in _find_expectations
  scoped to literally `!= 0` (never a specific nonzero N, which the real test never
  claims) + wired into determinex_local_oracle._check as a real enforcement, not just a
  recorded-but-ignored field.

Real A/B counterfactual across all three (measured against the actual HuggingFace
ProgramBench-Tests snapshot, scoped to each tool's real eval/tests/ directory):
  gomplate:   1003/617 (skipped) -> 1487/133   (recovered 484 examples)
  bedtools2:   978/116           -> 743/351    (net: fix 15 alone hit 992/102, but that
                                                 992 count included the wrong-argv bug this
                                                 test suite's positional-list-abort case
                                                 guards against -- 743/351 is the CORRECT,
                                                 hand-verified number after fix 16 recovers
                                                 the RESOURCES-file-arg cases fix 15 (d)
                                                 correctly left unresolved)
  run:         677/469           -> 843/303    (recovered 166 examples)
Hand-verified real recovered examples for both tools (test_annotate_single_file_fraction_
coverage, test_file_execution_simple) before trusting any of these counts -- confirmed full
correct argv, staged file content, and golden stdout, not just a nonzero recovery count.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _tree(src: str) -> ast.Module:
    return ast.parse(src)


# ---------- fix 15(a): base+args BinOp-Add shape ----------

_GOMPLATE_CONFTEST = """
import subprocess
import os
from pathlib import Path

EXECUTABLE = Path(__file__).parent.parent.parent / "executable"

import pytest

@pytest.fixture
def run_gomplate():
    def _run(args=None, stdin=None, env=None, cwd=None, timeout=30):
        if args is None:
            args = []
        cmd = [str(EXECUTABLE)] + args
        run_env = os.environ.copy()
        stdin_bytes = stdin.encode("utf-8") if stdin else None
        result = subprocess.run(cmd, input=stdin_bytes, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=run_env, cwd=cwd, timeout=timeout)
        return result.returncode, result.stdout.decode(), result.stderr.decode()
    return _run
"""


def test_discovers_base_for_binop_add_prefix_plus_args_shape():
    tree = _tree(_GOMPLATE_CONFTEST)
    kf = iox._discover_wrapper_kwarg_flags(tree, Path("conftest.py"))
    assert kf["run_gomplate"]["base"] == ["executable"]
    assert kf["run_gomplate"]["flags"] == {}


def test_extract_file_resolves_stdin_only_call_via_binop_base(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(_GOMPLATE_CONFTEST, encoding="utf-8")
    src = """
def test_index_first(run_gomplate):
    returncode, stdout, stderr = run_gomplate(stdin='{{ 1 }}')
    assert returncode == 0, stderr
    assert stdout == "1"
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable"]
    assert e.stdin == "{{ 1 }}"
    assert e.expect_rc == 0


# ---------- fix 15(a-variant): `[prefix] + list(*args)` (quickjs's *args shape) ----------

_QUICKJS_CONFTEST = """
import subprocess
from pathlib import Path

EXECUTABLE = Path(__file__).parent.parent.parent / "executable"

@pytest.fixture
def run_qjs():
    def _run(*args, input=None, timeout=10, check=False, **kwargs):
        cmd = [str(EXECUTABLE)] + list(args)
        return subprocess.run(cmd, input=input, capture_output=True, text=True,
                               timeout=timeout, check=check, **kwargs)
    return _run
"""


def test_discovers_base_for_list_star_args_shape():
    """quickjs's *args variant: `cmd = [str(EXECUTABLE)] + list(args)` -- the right-hand
    side is `list(args)` (a Call), not a bare Name like gomplate/bedtools2's `+ args`.
    Recovered quickjs from 969 remaining skips (out of ~4058 total) down to 173 once this
    shape resolved, on top of the already-built base+args BinOp handling."""
    tree = _tree(_QUICKJS_CONFTEST)
    kf = iox._discover_wrapper_kwarg_flags(tree, Path("conftest.py"))
    assert kf["run_qjs"]["base"] == ["executable"]


def test_extract_file_resolves_multi_positional_star_args_call(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(_QUICKJS_CONFTEST, encoding="utf-8")
    src = """
def test_eval_simple(run_qjs):
    result = run_qjs("--eval", "1+1")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "--eval", "1+1"]


# ---------- fix 15(b): module-level executable placeholder ----------


def test_extract_wrapper_base_argv_resolves_module_level_executable_ref():
    tree = _tree(_GOMPLATE_CONFTEST)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_gomplate":
            target = iox._find_returned_inner_closure(node)
            assert target is not None
            module_path_exprs = {
                stmt.targets[0].id: stmt.value
                for stmt in tree.body
                if isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
            }
            base, _suffix = iox._extract_wrapper_base_argv(target, {}, module_path_exprs)
            assert base == ["executable"]
            # without outer_path_exprs, the module-level EXECUTABLE name is invisible --
            # confirms this is genuinely a NEW resolution path, not already covered.
            assert iox._extract_wrapper_base_argv(target, {}, None) == (None, None)
            return
    raise AssertionError("run_gomplate fixture not found")


# ---------- fix 15(c)+(d): positional-list base-merge + unresolvable-list abort ----------

_BEDTOOLS_CONFTEST = """
import subprocess
from pathlib import Path

@pytest.fixture
def run_bedtools():
    def _run(args, stdin=None, check=True, timeout=30):
        executable = Path(__file__).parent.parent.parent / "executable"
        cmd = [str(executable)] + args
        result = subprocess.run(cmd, capture_output=True, input=stdin, cwd=None)
        return result
    return _run
"""


def test_positional_list_arg_prepends_base_not_replaces(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(_BEDTOOLS_CONFTEST, encoding="utf-8")
    src = """
def test_annotate_basic(run_bedtools):
    result = run_bedtools(["annotate", "-i", "a.bed"])
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "annotate", "-i", "a.bed"]


def test_unresolvable_positional_list_element_aborts_not_falls_to_base_only(tmp_path):
    """The costliest bug this fix exists to prevent: a positional list containing an
    element _resolve_list can't resolve (here, a bare unresolvable Name -- simulating a
    real-world unstageable file reference) must leave the test UNRESOLVED, never silently
    fall through to argv=[the wrapper's base only] with every real argument dropped."""
    conf = tmp_path / "conftest.py"
    conf.write_text(_BEDTOOLS_CONFTEST, encoding="utf-8")
    src = """
def test_annotate_with_unresolvable_arg(run_bedtools, some_completely_unresolvable_var):
    result = run_bedtools(["annotate", "-i", some_completely_unresolvable_var])
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 0
    assert "test_annotate_with_unresolvable_arg" in cov.skipped


# ---------- fix 16: RESOURCES-path-as-CLI-arg file staging ----------


def test_resolve_file_arg_reads_real_file_from_disk(tmp_path):
    resources = tmp_path / "test_resources" / "test_annotate"
    resources.mkdir(parents=True)
    (resources / "intervals.bed").write_bytes(b"chr1\t1\t2\n")
    test_file = tmp_path / "eval" / "tests" / "test_annotate.py"
    test_file.parent.mkdir(parents=True)
    src = (
        "from pathlib import Path\n"
        'RESOURCES = Path(__file__).parent.parent.parent / "test_resources" / "test_annotate"\n'
    )
    test_file.write_text(src, encoding="utf-8")
    resolver = iox._PathResolver(test_file)
    resolver.learn(ast.parse(src))
    node = ast.parse('str(RESOURCES / "intervals.bed")').body[0].value
    hit = resolver.resolve_file_arg(node)
    assert hit is not None
    basename, content = hit
    assert basename == "intervals.bed"
    assert content == "chr1\t1\t2\n"


def test_resolve_file_arg_returns_none_for_nonexistent_file(tmp_path):
    test_file = tmp_path / "test_x.py"
    src = 'from pathlib import Path\nRESOURCES = Path(__file__).parent / "test_resources"\n'
    test_file.write_text(src, encoding="utf-8")
    resolver = iox._PathResolver(test_file)
    resolver.learn(ast.parse(src))
    node = ast.parse('str(RESOURCES / "does_not_exist.bed")').body[0].value
    assert resolver.resolve_file_arg(node) is None


def test_extract_file_stages_real_resources_file_used_directly_as_argv(tmp_path):
    resources = tmp_path / "test_resources" / "test_annotate"
    resources.mkdir(parents=True)
    (resources / "intervals.bed").write_bytes(b"chr1\t1\t2\n")
    tests_dir = tmp_path / "eval" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "conftest.py").write_text(_BEDTOOLS_CONFTEST, encoding="utf-8")
    src = """
from pathlib import Path
RESOURCES = Path(__file__).parent.parent.parent / "test_resources" / "test_annotate"

def test_annotate_reads_real_file(run_bedtools):
    result = run_bedtools(["annotate", "-i", str(RESOURCES / "intervals.bed")])
    assert result.returncode == 0
"""
    f = tests_dir / "test_annotate.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "annotate", "-i", "intervals.bed"]
    assert e.files == {"intervals.bed": "chr1\t1\t2\n"}


# ---------- fix 17: expect_rc_nonzero ----------


def test_find_expectations_recognizes_rc_not_equal_zero():
    tree = _tree("""
def test_fails_on_bad_input(run_x):
    result = run_x(["--bad"])
    assert result.returncode != 0
""")
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "test_fails_on_bad_input"
    )
    resolver = iox._PathResolver(Path("test_x.py"))
    rc, exact, contains, ci, in_any, not_in, rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert rc is None
    assert rc_nonzero is True


def test_find_expectations_ignores_rc_not_equal_nonzero_literal():
    """`!= 1` (or any nonzero N) is a DIFFERENT, rarer claim -- the test never says WHICH
    nonzero code is expected, so this must NOT be conflated with expect_rc_nonzero."""
    tree = _tree("""
def test_specific_nonzero(run_x):
    result = run_x(["--bad"])
    assert result.returncode != 1
""")
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "test_specific_nonzero"
    )
    resolver = iox._PathResolver(Path("test_x.py"))
    rc, exact, contains, ci, in_any, not_in, rc_nonzero, _rc_in = iox._find_expectations(
        func, resolver
    )
    assert rc_nonzero is False


def test_extract_file_emits_example_for_rc_nonzero_only_assertion(tmp_path):
    src = """
def run_x(args=None):
    import subprocess
    return subprocess.run(["./executable"] + (args or []), capture_output=True)

def test_sort_order_violation():
    result = run_x(["closest", "-a", "bad.bed"])
    assert result.returncode != 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.expect_rc_nonzero is True
    assert e.expect_rc is None


def test_local_oracle_check_enforces_rc_nonzero():
    import determinex_local_oracle as loracle

    ex = iox.Example(test="t", argv=["x"], expect_rc_nonzero=True)
    ok, reason, detail = loracle._check(ex, rc=0, out="", err="")
    assert ok is False
    assert reason == "rc_nonzero"
    ok2, _, _ = loracle._check(ex, rc=1, out="", err="")
    assert ok2 is True
