"""Tests for the chained-wrapper-name and chained-return-shape discovery fixes
(2026-07-17), built after root-causing why yj/cheat/lua sat at 65-99% skip despite
already having the executable-fixture resolution (_fixture_return_const) and
inline-concat argv resolution (_resolve_list_concat) fixes: the fixtures TESTS
actually call (lua's run_lua_cmd, cheat's run_binary) never shell out THEMSELVES --
they call an ALREADY-discovered wrapper (run_lua, run_cheat) and forward their own
parameters. _discover_wrapper_names only recognized DIRECT shelling-out (a single,
non-iterative pass checking only the static RUN_NAMES set), so these delegating
names never entered run_names at all -- the test's own call to them was rejected
before argv resolution even started.

Fixed with FOUR coordinated pieces, all iterating a fixed point over the SAME
candidate FunctionDef list (this file + conftest.py/utils.py/etc):
  1. _discover_wrapper_names: a function that calls an ALREADY-known run name (not
     just the static RUN_NAMES) is now ALSO a run name.
  2. _extract_wrapper_base_argv: recognizes `return <call>([prefix] + args, ...)` --
     the base+args concatenation used INLINE as a call argument to a delegate
     wrapper, never bound to a local variable first (lua_cmd's whole body is one
     bare return statement).
  3. _discover_wrapper_return_shapes: a function whose sole body is `return
     <call>(...)` to an already-shaped name inherits that shape verbatim (a pure
     passthrough) -- otherwise `code, out, err = run_lua_cmd(...)` never gets a
     role mapping via run_lua_cmd's own name even after run_lua's tuple shape is
     known.
  4. _discover_wrapper_kwarg_flags' own target-detection (_shells_out_own_body) had
     the IDENTICAL single-pass/static-RUN_NAMES gap as _discover_wrapper_names --
     cheat's run_binary was correctly recognized as a run NAME by fix 1, but its
     BASE was never found (its nested closure calls `run_cheat(binary_path, args)`,
     itself only known via a prior fixed-point pass). Fixed the same way (a fixed-
     point loop re-checking _shells_out_own_body against the growing result set),
     plus a delegate-with-separate-params case: when the sole body is a bare
     `return <call>(...)` to an ALREADY-resolved wrapper (not a passthrough of the
     same args, not an inline concat -- run_cheat does the concatenation
     internally), inherit that wrapper's entire {base, flags} contract directly.
     This was the MOST DANGEROUS gap in the whole chain: it silently produced
     confidently-wrong examples (argv missing the executable placeholder
     entirely) that still counted as "resolved" in the aggregate recovery count --
     only caught by hand-inspecting real cheat examples, not by any test failure.

Also required resolving a bare Name parameter (lua's `lua_exec`, cheat's
`binary_path`) that matches a KNOWN EXECUTABLE FIXTURE (_fixture_return_const's
2026-07-17 executable-detection) as the 'executable' placeholder even when it's
just a parameter reference, not a path expression -- _extract_wrapper_base_argv's
new `exec_param_names` argument.

A real regression was caught and fixed along the way (not just reviewed by eye,
caught by the existing test suite immediately): once a plain top-level function
that directly shells out (`def run_command(args): return subprocess.run(
["./executable"] + args, ...)`) gained a learned base via the inline-concat
scanning, a genuinely-unresolvable control-flow-built argv (`args = [...]; if
cond: args.extend([...]); run_command(args)`) started resolving to
argv=['./executable'] -- confidently wrong, missing every real argument --
instead of staying correctly skipped. Fixed by tracking "a positional arg was
GIVEN but couldn't be resolved" (any type, not just List/BinOp) as its own
signal, distinct from "no positional arg was given at all" (the only case
where falling back to base-only is legitimate).

Real A/B, hand-verified (not just aggregate counts): cheat 30/298(skip 268)->
288/298(skip 10) -- 90%->3.4% skip. lua 1/147(skip 146)->121/147(skip 26) --
99%->18% skip. Confirmed the full 209-test pre-existing suite catches the
regression above via 4 tests whose expected argv now correctly includes the
base placeholder (updated, not suppressed) plus the conditional-argv test
which correctly stays at n_examples==0.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _tree(src: str) -> ast.Module:
    return ast.parse(src)


# ---------- fix 1: _discover_wrapper_names fixed-point chaining ----------


def test_discover_wrapper_names_finds_two_level_chain():
    tree = _tree("""
import subprocess

def run_lua(args, stdin=None):
    return subprocess.run(args, input=stdin, capture_output=True, text=True)

def run_lua_cmd(args):
    return run_lua(["executable"] + args)
""")
    names = iox._discover_wrapper_names(tree, Path("conftest.py"))
    assert names == {"run_lua", "run_lua_cmd"}


def test_discover_wrapper_names_single_pass_still_finds_direct_shellout():
    """A plain, non-chained direct shell-out is unaffected by the fixed-point loop --
    still found on the first pass, same as before this fix."""
    tree = _tree("""
import subprocess

def run(args):
    return subprocess.run(args, capture_output=True)
""")
    assert iox._discover_wrapper_names(tree, Path("conftest.py")) == {"run"}


def test_discover_wrapper_names_no_chain_when_target_never_shells_out():
    """A function that calls something NOT itself a known runner (and never
    resolves to one) must never be guessed into run_names."""
    tree = _tree("""
def helper(x):
    return format_output(x)

def format_output(x):
    return str(x).upper()
""")
    assert iox._discover_wrapper_names(tree, Path("conftest.py")) == set()


# ---------- fix 2: inline-concat base discovery for delegating closures ----------

_LUA_CMD_CONFTEST = """
import subprocess
import pytest
from pathlib import Path

EXECUTABLE = str(Path(__file__).parent.parent.parent / "executable")

@pytest.fixture
def lua_exec():
    return EXECUTABLE

def run_lua(args, stdin=None):
    return subprocess.run(args, input=stdin, capture_output=True, text=True)

@pytest.fixture
def run_lua_cmd(lua_exec):
    def _run(args, stdin=None):
        return run_lua([lua_exec] + args, stdin=stdin)
    return _run
"""


def test_extract_wrapper_base_argv_finds_inline_concat_in_bare_return():
    tree = _tree(_LUA_CMD_CONFTEST)
    kf = iox._discover_wrapper_kwarg_flags(tree, Path("conftest.py"))
    assert kf["run_lua_cmd"]["base"] == ["executable"]


def test_discover_wrapper_names_chains_through_nested_closure_delegate():
    """The real corpus shape (lua/cheat): the OUTER fixture never shells out itself, its
    RETURNED INNER CLOSURE calls an already-known wrapper. Confirms _shells_out (used by
    _discover_wrapper_names) resolves through _find_returned_inner_closure, not just its
    own body -- a direct, non-nested delegation (no inner def at all) is a DIFFERENT,
    unbuilt shape and correctly stays unrecognized."""
    tree = _tree(_LUA_CMD_CONFTEST)
    names = iox._discover_wrapper_names(tree, Path("conftest.py"))
    assert {"run_lua", "run_lua_cmd"} <= names


def test_extract_file_resolves_call_through_delegating_fixture(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(_LUA_CMD_CONFTEST, encoding="utf-8")
    src = """
def test_version(run_lua_cmd):
    result = run_lua_cmd(["-v"])
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "-v"]


# ---------- fix 3: chained return-shape inheritance ----------

_TUPLE_SHAPE_CONFTEST = """
import subprocess

def run_lua(args, stdin=None):
    result = subprocess.run(args, input=stdin, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr

def run_lua_cmd(args):
    return run_lua(["executable"] + args)
"""


def test_discover_wrapper_return_shapes_inherits_through_passthrough():
    tree = _tree(_TUPLE_SHAPE_CONFTEST)
    shapes = iox._discover_wrapper_return_shapes(tree, Path("conftest.py"))
    assert shapes["run_lua"] == {"rc_pos": 0, "stdout_pos": 1, "stderr_pos": 2}
    assert shapes["run_lua_cmd"] == shapes["run_lua"]


def test_extract_file_resolves_tuple_unpack_through_delegating_wrapper(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(_TUPLE_SHAPE_CONFTEST, encoding="utf-8")
    src = """
def test_version(run_lua_cmd=run_lua_cmd):
    code, out, err = run_lua_cmd(["-v"])
    assert code == 0
    assert out == "1.0\\n"
"""
    # run_lua_cmd isn't a fixture here (plain default-arg reference for a minimal
    # repro) -- what matters is that the tuple-unpack role mapping resolves through
    # run_lua_cmd's inherited shape, not run_lua's own name.
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.expect_rc == 0
    assert e.expect_stdout == "1.0\n"


# ---------- fix 4: executable-fixture PARAMETER resolution in base discovery ----------


def test_extract_wrapper_base_argv_resolves_bare_exec_param():
    src = """
import pytest
from pathlib import Path

@pytest.fixture
def binary_path():
    return Path(__file__).parent.parent.parent / "executable"

def run_cheat(binary_path, args):
    import subprocess
    return subprocess.run([str(binary_path)] + args, capture_output=True)

@pytest.fixture
def run_binary(binary_path):
    def _run(args):
        return run_cheat(binary_path, args)
    return _run
"""
    tree = ast.parse(src)
    kf = iox._discover_wrapper_kwarg_flags(tree, Path("conftest.py"))
    assert kf["run_cheat"]["base"] == ["executable"]
    assert kf["run_binary"]["base"] == ["executable"]


def test_extract_file_delegate_with_separate_params_includes_base_end_to_end(tmp_path):
    """The real bug this fix exists to prevent, caught only by hand-checking output, not
    the aggregate recovery count: cheat's run_binary(binary_path) closure calls
    `run_cheat(binary_path, args)` -- binary_path and args passed as SEPARATE positional
    arguments (run_cheat concatenates them internally), not an inline concat and not a
    pure passthrough. Before this fix, run_binary was correctly recognized as a run NAME
    (via _discover_wrapper_names) but its BASE was never found, so every example silently
    dropped the executable placeholder entirely (argv=['--version'] instead of
    ['executable', '--version']) while still counting as 'resolved' in the aggregate."""
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import pytest
import subprocess
from pathlib import Path

@pytest.fixture
def binary_path():
    return Path(__file__).parent.parent.parent / "executable"

def run_cheat(binary_path, args):
    return subprocess.run([str(binary_path)] + args, capture_output=True)

@pytest.fixture
def run_binary(binary_path):
    def _run(args):
        return run_cheat(binary_path, args)
    return _run
""",
        encoding="utf-8",
    )
    src = """
def test_version_flag(run_binary):
    result = run_binary(["--version"])
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "--version"]


# ---------- fix 5 (the real regression this session caught): unresolvable positional
#             arg must abort, never fall back to base-only ----------


def test_control_flow_built_argv_stays_unresolved_even_with_learned_base(tmp_path):
    """The exact regression this fix chain introduced and then fixed: once a plain
    direct-shellout wrapper gains a learned base (from the inline-concat scan), a
    positional arg that exists but is unresolvable (built via runtime control flow)
    must still abort the whole candidate -- never silently produce argv=[base only],
    silently dropping every real argument."""
    src = """
import subprocess

def run_command(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

def test_conditional(flag_value):
    args = [flag_value, "-c", "test"]
    if not flag_value.startswith("--output"):
        args.extend(["-o", "test.png"])
    result = run_command(args)
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 0
    assert "test_conditional" in cov.skipped


def test_learned_base_wrapper_with_resolvable_positional_list_still_works(tmp_path):
    """Sanity check alongside the regression test above: a RESOLVABLE positional list
    on the same kind of learned-base wrapper must still correctly include the base."""
    src = """
import subprocess

def run_command(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

def test_help():
    result = run_command(["--help"])
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    # "executable" placeholder now correctly resolved (fix 40, 2026-07-17):
    # _is_executable_path_expr now also recognizes a bare string literal with
    # slashes baked in ("./executable"), not just a BinOp/Div chain.
    assert cov.examples[0].argv == ["executable", "--help"]
