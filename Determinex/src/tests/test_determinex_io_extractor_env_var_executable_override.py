"""Test for fix 35 (2026-07-17): an environment-variable override with a
Path-expression/string fallback for the executable path.

Root-caused via gdal (158/603 examples, still low even after fix 34): its whole
conftest.py declares `EXECUTABLE = os.environ.get('GDAL_EXECUTABLE',
str(Path(__file__).parent.parent.parent / "executable"))` -- lets the harness
override the binary location via env var while defaulting to the standard
placeholder convention. Neither _is_executable_path_expr nor fix 32's plain-string
check unwraps an os.environ.get()/os.getenv() CALL at all, so `run`'s base
resolution still failed even with all of fixes 24-34 applied.

Fixed by unwrapping the DEFAULT argument (second positional arg, or a `default=`
keyword) of an os.environ.get()/os.getenv() call and applying the SAME
Path-expression and plain-string basename checks to that expression instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_extract_wrapper_base_argv_resolves_env_get_with_path_expr_default():
    tree = iox.ast.parse("""
import subprocess
import os
from pathlib import Path

EXECUTABLE = os.environ.get("GDAL_EXECUTABLE", str(Path(__file__).parent.parent.parent / "executable"))

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


def test_extract_wrapper_base_argv_resolves_env_get_with_plain_string_default():
    """The default can also be a bare string constant (samtools/fix-32 style),
    not just a Path expression."""
    tree = iox.ast.parse("""
import subprocess
import os

EXECUTABLE = os.environ.get("MY_EXECUTABLE", "/workspace/executable")

def run(*args, timeout=5.0):
    return subprocess.run([EXECUTABLE, *args], capture_output=True, timeout=timeout)
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
    assert base == ["executable"]


def test_extract_wrapper_base_argv_declines_env_get_with_unrelated_default():
    """Conservative guard: an os.environ.get() default whose basename isn't
    'executable' must never be treated as the placeholder."""
    tree = iox.ast.parse("""
import subprocess
import os

DATA_FILE = os.environ.get("DATA_PATH", "/workspace/data.txt")

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


def test_extract_file_resolves_gdal_shaped_env_override_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import os
from pathlib import Path

EXECUTABLE = os.environ.get("GDAL_EXECUTABLE", str(Path(__file__).parent.parent.parent / "executable"))

def run(*args, stdin=None, env=None, cwd=None, timeout=5.0):
    return subprocess.run(
        [EXECUTABLE, *args],
        input=stdin.encode() if isinstance(stdin, str) else stdin,
        capture_output=True, timeout=timeout,
    )
""",
        encoding="utf-8",
    )
    src = """
from conftest import run

def test_version():
    result = run("--version")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "--version"]
