"""Test for fix 32 (2026-07-17): a bare STRING CONSTANT executable-path convention,
never built via a Path(...)./ chain at all.

Root-caused via samtools (66/476 examples pre-fix, second-worst-recovered tool
sampled this session, same `run(*args)` shape as caps-log/fix 31): its whole
conftest.py declares `EXECUTABLE = "/workspace/executable"` -- a PLAIN string
literal, not `Path(__file__).parent... / "executable"` (the shape
_is_executable_path_expr's BinOp/Div-unwrapping loop expects). Even with fix 31's
Starred-vararg handling, `is_exec_ref` still returned False for this Name (its bound
expression is an ast.Constant, never entering the BinOp loop at all), so base
resolution still failed and `run("view", "--help")` still resolved to
argv=['view','--help'], missing the executable entirely.

Fixed by extending is_exec_ref's local_path_exprs lookup: after the existing
_is_executable_path_expr check, also resolve the bound expression via _const() and
check whether its VALUE's basename (splitting on both '/' and '\\', matching either
platform's convention) equals "executable" -- the oracle's own
_drop_binary_placeholder convention only cares about the basename, so this is exactly
as safe as the existing Path-expression check, just reached via a literal string
instead of a BinOp chain.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_extract_wrapper_base_argv_resolves_plain_string_executable_constant():
    tree = iox.ast.parse("""
import subprocess

EXECUTABLE = "/workspace/executable"

def run(*args, timeout=5.0):
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


def test_extract_wrapper_base_argv_declines_plain_string_not_named_executable():
    """Conservative guard: an ordinary string constant whose basename ISN'T
    'executable' must NEVER be treated as the placeholder -- correctly stays
    unresolved here (a plain module-level constant's own value isn't visible to
    _extract_wrapper_base_argv's extra_vars, an unrelated pre-existing limitation),
    proving fix 32's basename check doesn't over-match unrelated constants."""
    tree = iox.ast.parse("""
import subprocess

DATA_FILE = "/workspace/data.txt"

def run(*args, timeout=5.0):
    return subprocess.run([DATA_FILE, *args], capture_output=True, timeout=timeout)
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    module_path_exprs = {
        stmt.targets[0].id: stmt.value
        for stmt in tree.body
        if isinstance(stmt, iox.ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], iox.ast.Name)
    }
    base, suffix = iox._extract_wrapper_base_argv(func, {}, module_path_exprs, set())
    assert base is None


def test_extract_file_resolves_samtools_shaped_direct_import_call(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import os

EXECUTABLE = "/workspace/executable"

def run(*args, stdin=None, env=None, cwd=None, timeout=5.0):
    return subprocess.run(
        [EXECUTABLE, *args],
        input=stdin.encode() if isinstance(stdin, str) else stdin,
        capture_output=True, timeout=timeout, env=os.environ.copy(), cwd=cwd,
    )
""",
        encoding="utf-8",
    )
    src = """
from conftest import run

def test_view_help():
    result = run("view", "--help")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "view", "--help"]
