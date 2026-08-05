"""Tests for determinex_io_extractor.py's wrapper-closure keyword-to-flag introspection
plus tmp_path/tmpdir scratch-path relativization (2026-07-17), the fourteenth fix in the
skip-rate chain -- the single largest deliberate build this session, after being sized and
initially deferred (see io_extractor_duckdb_kwarg_closure_lead_20260717 in
build_knowledge.json) then built once explicitly encouraged to push further.

Continuing the corpus-wide audit past fix 13, duckdb was the worst-performing tool in the
entire 201-tool corpus once correctly scoped to eval/tests/ (24/746 = 3.2% resolved). Root
cause: `run_duckdb(sql='...')` -- a fixture-factory whose returned closure builds
`cmd = [str(executable), temp_db]; if args: cmd.extend(args); if sql: cmd.extend(["-c",
sql])`. Sized: 4005 of 4015 total run_duckdb(...) calls use the sql= keyword. THREE
mechanisms were needed together:

(1) _track_scratch_path_fixtures -- a fixture yielding `str(tmp_path / "literal")` (pytest's
    own built-in fresh-per-test temp-dir fixtures) resolves to just the literal basename,
    since determinex_local_oracle.py already runs every Example in a fresh per-call uuid
    rundir -- a bare relative basename naturally lands in a fresh, empty location with ZERO
    oracle-side changes needed. Verified by reading _run_reimpl before assuming this was
    safe, not guessed.
(2) _discover_wrapper_kwarg_flags -- learns, from a runner's OWN body (or a returned inner
    closure's, the fixture-factory shape), which of its keyword params map to a literal CLI
    flag (`if sql: cmd.extend(["-c", sql])` -> {"sql": "-c"}), AND the wrapper's own fixed
    base argv elements (`cmd = [str(executable), temp_db]` -> ["executable", "test.db"],
    resolving the 'executable' placeholder even when it's bound to a local variable one
    assignment earlier rather than written inline).
(3) A real bug caught by hand-checking output, not just the aggregate count:
    `run_duckdb(args=["--csv"], sql="...")` initially lost BOTH the base and the sql-
    derived flag, because the existing ARGS_KW keyword handling REPLACES argv wholesale
    (designed for the simple `run(args=[...])` shape where args IS the entire invocation)
    -- for a wrapper with a learned base+flags contract, ARGS_KW must instead APPEND to the
    base like the wrapper's own `cmd.extend(args)` does. Fixed by branching on whether this
    specific runner name has learned wrapper info before choosing append-vs-replace
    semantics, so every OTHER tool's existing ARGS_KW behavior is untouched.

Real A/B counterfactual: duckdb went from 24/746 (3.2%) to 279/746 (37.4%) resolved.
Hand-verified a random sample of 15 recovered examples for correctness (argv element
order, SQL text, flag placement) before trusting the aggregate count -- caught the
append-vs-replace bug this way, which the recovery COUNT alone did not change (255 before
and after that specific fix) but which would have silently produced wrong Examples for
every combined args=+sql= call had it shipped uncaught.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _tree(src: str) -> ast.Module:
    return ast.parse(src)


# ---------- _track_scratch_path_fixtures() ----------


def test_scratch_path_fixture_resolves_tmp_path_basename():
    tree = _tree("""
@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    yield str(db_path)
""")
    assert iox._track_scratch_path_fixtures(tree) == {"temp_db": "test.db"}


def test_scratch_path_fixture_supports_tmpdir_too():
    tree = _tree("""
@pytest.fixture
def temp_db(tmpdir):
    db_path = tmpdir / "scratch.db"
    return str(db_path)
""")
    assert iox._track_scratch_path_fixtures(tree) == {"temp_db": "scratch.db"}


def test_scratch_path_fixture_rejects_non_tmp_base():
    """A base that ISN'T pytest's own tmp_path/tmpdir must never be relativized -- e.g.
    RESOURCES/'golden.txt' is a real, fixed content path _PathResolver already resolves
    correctly; treating it as a scratch location would be wrong."""
    tree = _tree("""
@pytest.fixture
def golden(RESOURCES):
    p = RESOURCES / "golden.txt"
    return str(p)
""")
    assert iox._track_scratch_path_fixtures(tree) == {}


def test_scratch_path_fixture_requires_str_or_bare_return():
    tree = _tree("""
@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    return db_path.resolve()
""")
    assert iox._track_scratch_path_fixtures(tree) == {}


# ---------- _discover_wrapper_kwarg_flags() ----------

_DUCKDB_CONFTEST = """
import subprocess

WORKSPACE_ROOT = __import__("pathlib").Path(__file__).parent

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    yield str(db_path)

@pytest.fixture
def run_duckdb(temp_db):
    def _run(args=None, sql=None, stdin=None, expect_error=False):
        executable = WORKSPACE_ROOT / "executable"
        cmd = [str(executable), temp_db]
        if args:
            cmd.extend(args)
        if sql:
            cmd.extend(["-c", sql])
        input_data = stdin.encode() if stdin else None
        result = subprocess.run(cmd, capture_output=True, input=input_data)
        return result
    return _run
"""


def test_discovers_kwarg_flag_and_base_for_fixture_factory():
    tree = _tree(_DUCKDB_CONFTEST)
    kf = iox._discover_wrapper_kwarg_flags(tree, Path("conftest.py"))
    # run_duckdb's own `if args: cmd.extend(args)` is ALSO a valid passthrough shape
    # (fix 26, 2026-07-17) -- harmless here since ARGS_KW's dedicated handling in
    # _find_run_call takes priority over this_kwarg_flags for the "args" keyword
    # specifically, so real resolution behavior is unaffected.
    assert kf["run_duckdb"]["flags"] == {"sql": "-c", "args": iox._KWARG_PASSTHROUGH}
    assert kf["run_duckdb"]["base"] == ["executable", "test.db"]


def test_executable_placeholder_resolves_one_assignment_removed():
    """The 'executable' path is often assigned to a local var one line before the cmd
    list literal, not written inline -- both must resolve to the same placeholder."""
    tree = _tree("""
import subprocess

@pytest.fixture
def run_x():
    def _run(sql=None):
        p = __import__("pathlib").Path(".") / "executable"
        cmd = [str(p)]
        if sql:
            cmd.extend(["-c", sql])
        return subprocess.run(cmd, capture_output=True)
    return _run
""")
    kf = iox._discover_wrapper_kwarg_flags(tree, Path("test_x.py"))
    assert kf["run_x"]["base"] == ["executable"]


def test_no_flags_or_base_means_no_entry():
    tree = _tree("""
def helper():
    return 42
""")
    assert iox._discover_wrapper_kwarg_flags(tree, Path("test_x.py")) == {}


# ---------- extract_file() integration: end-to-end duckdb shape ----------


def test_extract_file_resolves_sql_only_call(tmp_path):
    src = (
        _DUCKDB_CONFTEST
        + """
def test_simple_sql(run_duckdb):
    result = run_duckdb(sql="SELECT 1 + 1;")
    assert result.returncode == 0
    assert "2" in result.stdout.decode()
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "test.db", "-c", "SELECT 1 + 1;"]
    assert e.expect_rc == 0
    assert "2" in e.expect_in


def test_extract_file_combined_args_and_sql_appends_not_replaces(tmp_path):
    """The regression this fix specifically exists to prevent: args= must APPEND to the
    wrapper's own base, never wholesale-replace argv and silently drop the base + the
    sql-derived flag."""
    src = (
        _DUCKDB_CONFTEST
        + """
def test_csv_output(run_duckdb):
    result = run_duckdb(args=["--csv"], sql="SELECT 1 as a, 2 as b;")
    assert result.returncode == 0
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "test.db", "--csv", "-c", "SELECT 1 as a, 2 as b;"]


def test_extract_file_plain_run_args_kw_unaffected_by_learned_wrappers(tmp_path):
    """A completely unrelated tool's plain `run(args=[...])` call (the ORIGINAL,
    general-purpose ARGS_KW behavior) must still wholesale-replace argv exactly as
    before -- this fix must not change behavior for runners it never learned anything
    about."""
    src = """
import subprocess

def run(args=None):
    return subprocess.run(["./executable"] + (args or []), capture_output=True)

def test_x():
    result = run(args=["--help"])
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["--help"]
