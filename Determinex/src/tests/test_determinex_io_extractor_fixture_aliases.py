"""Tests for determinex_io_extractor.py's fixture-wrapper-alias discovery (2026-07-16),
the tenth fix in the skip-rate chain -- and the single largest single-fix recovery this
session.

Found while checking whether xh (68.5% skip after fixes 1-9) had a second cause beyond the
already-identified http_server network-mock-server category. A broad sample of xh's skips
turned up test_nested_json.py entirely unresolved (0/56 tests), despite looking like a
plain, simple case:

    def run_xh(*args, ...):              # plain function, real subprocess.run() impl
        ...
        return subprocess.run(cmd, ...)
    _run_xh_func = run_xh                # captured BEFORE the name gets shadowed below
    @pytest.fixture
    def xh():
        \"\"\"docstring\"\"\"
        return _run_xh_func
    @pytest.fixture
    def run_xh():                        # SAME NAME as the plain function above -- a
        ...                              # different fixture shadowing it, unrelated here
        return _run

    def test_simple_nested_object(xh):
        result = xh('--print=B', '--offline', '--ignore-stdin', ':', 'a[b]=value')
        assert result.returncode == 0

_discover_wrapper_names correctly finds "run_xh" (the plain function directly shells out).
But the test calls `xh(...)`, not `run_xh(...)` -- and `_shells_out`/_discover_wrapper_names
only look for a function whose body directly CALLS subprocess/a known runner; a fixture
whose entire body is `return _run_xh_func` has no Call node anywhere in it, so "xh" was
never added as a resolvable runner name, even though it is transparently just another name
for the exact same real function.

Fix: _discover_fixture_wrapper_aliases() resolves ONE hop of simple module-level
`alias = name` assignment (`_run_xh_func = run_xh`) so a @pytest.fixture's bare
`return <name>` reaches a name already known to be a runner, then registers the fixture's
OWN name as an additional alias for this file's resolution. First attempt incorrectly
required the fixture body to be exactly one statement (`len(node.body) != 1`) -- broke
immediately on real data because `xh`'s fixture has a docstring before the `return`, a
near-universal pattern for fixtures. Fixed by skipping a leading string-literal-Expr
docstring before checking body shape.

Real A/B counterfactual (never AST-presence counting alone): test_nested_json.py alone
went from 0/56 to 56/56 examples -- full recovery of an entire file. Across xh's whole
directory (one branch): 306->516 examples (+210) of 917 tests. Across the full 6-tool
re-scan (3 branches each): xh 318->529 examples, skip rate 68.5%->47.7% -- the single
largest recovery of any fix in this chain. Other 5 tools unchanged in this specific fix
(the alias-collision pattern happens to be xh-specific in the sampled branches, though the
mechanism is general and will apply to any tool using the same idiom).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402

# ---------- _discover_fixture_wrapper_aliases() ----------


def test_discovers_simple_one_hop_alias(tmp_path):
    src = '''
import subprocess

def run_xh(*args):
    return subprocess.run(["./executable", *args], capture_output=True, text=True)

_run_xh_func = run_xh

@pytest.fixture
def xh():
    """Fixture docstring."""
    return _run_xh_func
'''
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    tree = ast.parse(src)
    known = iox._discover_wrapper_names(tree, f)
    assert "run_xh" in known
    aliases = iox._discover_fixture_wrapper_aliases(tree, f, iox.RUN_NAMES | known)
    assert aliases == {"xh": "run_xh"}


def test_discovers_alias_without_intermediate_assignment(tmp_path):
    """A fixture that returns the runner name directly (no `_run_xh_func = run_xh` step)
    must also resolve -- the assignment hop is optional, not required."""
    src = """
import subprocess

def run_xh(*args):
    return subprocess.run(["./executable", *args], capture_output=True, text=True)

@pytest.fixture
def xh():
    return run_xh
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    tree = ast.parse(src)
    known = iox._discover_wrapper_names(tree, f)
    aliases = iox._discover_fixture_wrapper_aliases(tree, f, iox.RUN_NAMES | known)
    assert aliases == {"xh": "run_xh"}


def test_rejects_fixture_returning_unrelated_name(tmp_path):
    src = """
@pytest.fixture
def sample_text():
    unrelated = "hello world"
    return unrelated
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    tree = ast.parse(src)
    aliases = iox._discover_fixture_wrapper_aliases(tree, f, iox.RUN_NAMES)
    assert aliases == {}


def test_rejects_non_fixture_function_returning_a_runner_name(tmp_path):
    src = """
def run_xh(*args):
    return subprocess.run(["./executable", *args])

def helper():
    return run_xh
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    tree = ast.parse(src)
    known = iox._discover_wrapper_names(tree, f)
    aliases = iox._discover_fixture_wrapper_aliases(tree, f, iox.RUN_NAMES | known)
    assert aliases == {}


def test_fixture_body_with_multiple_statements_before_return_bails(tmp_path):
    """Only a bare `return <name>` (docstring aside) is trusted -- any real logic before
    the return means the fixture isn't a transparent alias; never guess past that."""
    src = """
def run_xh(*args):
    return subprocess.run(["./executable", *args])

@pytest.fixture
def xh():
    setup_something()
    return run_xh
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    tree = ast.parse(src)
    known = iox._discover_wrapper_names(tree, f)
    aliases = iox._discover_fixture_wrapper_aliases(tree, f, iox.RUN_NAMES | known)
    assert aliases == {}


def test_bare_fixture_decorator_name_supported(tmp_path):
    src = """
from pytest import fixture

def run_xh(*args):
    return subprocess.run(["./executable", *args])

@fixture
def xh():
    return run_xh
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    tree = ast.parse(src)
    known = iox._discover_wrapper_names(tree, f)
    aliases = iox._discover_fixture_wrapper_aliases(tree, f, iox.RUN_NAMES | known)
    assert aliases == {"xh": "run_xh"}


# ---------- extract_file() integration ----------


def test_extract_file_resolves_test_calling_fixture_alias_directly(tmp_path):
    src = '''
import subprocess

def run_xh(*args):
    return subprocess.run(["./executable", *args], capture_output=True, text=True)

_run_xh_func = run_xh

@pytest.fixture
def xh():
    """Docstring."""
    return _run_xh_func

def test_simple_call(xh):
    result = xh("--version")
    assert result.returncode == 0
'''
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.test == "test_simple_call"
    # "./executable" now correctly prepended (fix 33, 2026-07-17): the alias "xh" now
    # inherits run_xh's own already-learnable base contract -- previously xh had NO
    # base at all (is_learned_wrapper=False), so xh("--version")'s own arg silently
    # became the WHOLE argv.
    # "executable" placeholder now correctly resolved (fix 40, 2026-07-17):
    # _is_executable_path_expr now also recognizes a bare string literal with
    # slashes baked in ("./executable"), not just a BinOp/Div chain.
    assert e.argv == ["executable", "--version"]
    assert e.expect_rc == 0


def test_extract_file_unrelated_fixture_of_same_shape_stays_unresolved(tmp_path):
    """A fixture that transparently returns an UNRELATED (non-runner) function must not be
    treated as a runner alias just because it matches the bare-return shape."""
    src = """
def make_sample():
    return "hello"

@pytest.fixture
def sample():
    return make_sample

def test_uses_sample(sample):
    assert sample() == "hello"
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 0
    assert cov.skipped == ["test_uses_sample"]
