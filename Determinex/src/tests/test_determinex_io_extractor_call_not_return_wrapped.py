"""Test for fix 34 (2026-07-17): a wrapper's real subprocess call is assigned to a
local variable FIRST, then returned separately -- not a direct `return
subprocess.run(...)`.

Root-caused via htop (and 9 other tools sharing the exact gap: yq, gdal, dust,
tparse, bartib, ethabi, xcp, serpl, goimports-reviser -- found via a corpus-wide
static audit for the "discovered run-name never got a learned base" precondition,
scratchpad/audit_unlearned_wrappers.py). htop's whole conftest.py:

    def run(*args, stdin=None, env=None, cwd=None, timeout=5.0, check=False):
        ...
        try:
            result = subprocess.run(
                [EXECUTABLE, *args],
                input=..., capture_output=True, timeout=timeout, env=full_env,
                cwd=cwd, check=check,
            )
            return result
        except subprocess.TimeoutExpired as e:
            class TimeoutResult:
                ...
            return TimeoutResult()

Fixes 26/27/29/30/31/32/33's "CHAINED-WRAPPER INLINE CONCAT"/Starred-vararg scan
required `isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call)` -- a
bare `return result` has `stmt.value` as a Name, never a Call, so this entire shape
was invisible regardless of how `[EXECUTABLE, *args]` itself was built (even though
fix 31's Starred-handling and fix 32's plain-string-executable-constant handling
would otherwise both apply). base/flags stayed unresolved, "run" was never a
learned wrapper, and `run("-H", "--help")` resolved to argv=['-H','--help'],
missing the executable entirely -- a confidently WRONG example, not a skip.

Fixed by widening the scan to walk EVERY Call node directly (dropping the
Return-wrapper requirement) -- the call's own arguments are what matter, not
whether its result is returned directly, assigned to a variable first (any number
of statements away), or ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_extract_wrapper_base_argv_resolves_assign_then_return_shape():
    tree = iox.ast.parse("""
import subprocess

EXECUTABLE = "./executable"

def run(*args, timeout=5.0):
    try:
        result = subprocess.run([EXECUTABLE, *args], capture_output=True, timeout=timeout)
        return result
    except subprocess.TimeoutExpired:
        return None
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


def test_extract_file_resolves_htop_shaped_try_except_wrapper_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import os

EXECUTABLE = "./executable"

def run(*args, stdin=None, env=None, cwd=None, timeout=5.0, check=False):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    try:
        result = subprocess.run(
            [EXECUTABLE, *args],
            input=stdin.encode() if isinstance(stdin, str) else stdin,
            capture_output=True, timeout=timeout, env=full_env, cwd=cwd, check=check,
        )
        return result
    except subprocess.TimeoutExpired:
        class TimeoutResult:
            def __init__(self):
                self.returncode = -1
        return TimeoutResult()
""",
        encoding="utf-8",
    )
    src = """
from conftest import run

def test_help():
    result = run("-H", "--help")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "-H", "--help"]
