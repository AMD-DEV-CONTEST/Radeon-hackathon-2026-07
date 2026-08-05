"""Test for fix 31 (2026-07-17): a `[prefix, *args]` list literal (Starred unpack of
the wrapper's own vararg parameter), semantically identical to the already-handled
`[prefix] + list(args)` BinOp-concat shape but written as a list-literal unpack.

Root-caused via caps-log's whole conftest.py (26/343 examples, the worst-recovered
tool sampled this session):

    WORKSPACE_ROOT = Path(__file__).parent.parent.parent
    EXECUTABLE = str(WORKSPACE_ROOT / "executable")

    def run(*args, stdin=None, env=None, cwd=None, timeout=5.0):
        return subprocess.run(
            [EXECUTABLE, *args],
            input=stdin.encode() if isinstance(stdin, str) else stdin,
            capture_output=True, timeout=timeout, env=full_env, cwd=cwd,
        )

`run` is already a hardcoded RUN_NAME, and every test calls it directly (often via
`from conftest import run`, no fixture indirection at all: `result = run("-h")`).
Neither existing base-learning scan recognized `ast.Starred` inside a List literal
(resolve_list_literal's per-element loop has no Starred handling at all), so base and
flags both failed to resolve -- "run" was never registered as a learned wrapper, and
the call's own single argument became the ENTIRE argv: `['-h']`, missing the
executable path entirely -- a confidently WRONG example, not a skip.

Fixed by recognizing a List literal whose LAST element is `ast.Starred(value=Name)`
matching the wrapper's own `*args` parameter (`target.args.vararg`), treating
everything before it as the base -- scoped to the vararg being the list's final
element only, mirroring fix 29's own-param-tail conservatism.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_extract_wrapper_base_argv_resolves_starred_vararg():
    tree = iox.ast.parse("""
import subprocess
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).parent.parent.parent
EXECUTABLE = str(WORKSPACE_ROOT / "executable")

def run(*args, stdin=None, timeout=5.0):
    return subprocess.run([EXECUTABLE, *args], capture_output=True, timeout=timeout)
""")
    func = next(
        n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef) and n.name == "run"
    )
    module_path_exprs = {
        stmt.targets[0].id: stmt.value
        for stmt in tree.body
        if isinstance(stmt, iox.ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], iox.ast.Name)
    }
    base, suffix = iox._extract_wrapper_base_argv(func, {}, module_path_exprs, set())
    assert base == ["executable"]
    assert suffix is None


def test_extract_wrapper_base_argv_declines_starred_of_unrelated_name():
    """Conservative guard: a Starred element NOT matching the wrapper's own vararg
    parameter must never be treated as the passthrough slot. No other list literal
    exists in this function body, so a wrongly-permissive match would be the ONLY
    way `base` comes back non-None here."""
    tree = iox.ast.parse("""
import subprocess

def run(*args):
    return subprocess.run(["executable", *other_name], capture_output=True)
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    base, suffix = iox._extract_wrapper_base_argv(func, {}, {}, set())
    assert base is None
    assert suffix is None


def test_extract_file_resolves_capslog_shaped_direct_import_call(tmp_path):
    """caps-log's real idiom: `run` imported directly (no fixture parameter at all)
    and called bare in the test body."""
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).parent.parent.parent
EXECUTABLE = str(WORKSPACE_ROOT / "executable")

def run(*args, stdin=None, env=None, cwd=None, timeout=5.0):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [EXECUTABLE, *args],
        input=stdin.encode() if isinstance(stdin, str) else stdin,
        capture_output=True, timeout=timeout, env=full_env, cwd=cwd,
    )
""",
        encoding="utf-8",
    )
    src = """
from conftest import run

def test_help_flag_short():
    result = run("-h")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "-h"]
