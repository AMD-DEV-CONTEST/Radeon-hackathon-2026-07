"""Test for fix 29 (2026-07-17): a wrapper whose ENTIRE argv is a single list literal
passed DIRECTLY as a call argument (never bound to a variable, never a `[prefix] +
args` concatenation), where the list's TAIL is the wrapper's own parameter(s).

Root-caused via ditaa's whole test_stringutils.py:

    WORKSPACE = Path(__file__).parent.parent.parent
    EXECUTABLE = WORKSPACE / "executable"

    def run_java_class(classname, timeout=10):
        result = subprocess.run(
            ["java", "-cp", str(EXECUTABLE), classname],
            capture_output=True, text=True, timeout=timeout
        )
        return result

    def test_string_utils_main():
        result = run_java_class("org.stathissideris.ascii2image.text.StringUtils")

Before this fix, neither of _extract_wrapper_base_argv's existing scans matched this
shape (not a `cmd = [...]` assignment, not a `[prefix] + args` BinOp concat) -- base
and flags both came back empty, so run_java_class was never registered as a learned
wrapper at all. At the call site, its own argument was then treated AS the real argv
directly (the un-learned "run(*args) style" fallback): argv=['org.stathissideris...']
with "java"/"-cp"/the executable path silently MISSING -- a confidently WRONG example,
not a skip (would try to execute a bare classname as argv[0]).

Fixed by scanning for a Call whose first arg is a List literal containing a bare Name
matching one of the wrapper's own parameters, learning everything BEFORE that
reference as `this_base` -- scoped conservatively to require the own-parameter
reference(s) form a contiguous TAIL (nothing fixed follows), matching the existing
additive `this_base + pos_strs` model exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_extract_wrapper_base_argv_resolves_own_param_tail():
    tree = iox.ast.parse("""
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent.parent
EXECUTABLE = WORKSPACE / "executable"

def run_java_class(classname, timeout=10):
    result = subprocess.run(
        ["java", "-cp", str(EXECUTABLE), classname],
        capture_output=True, text=True, timeout=timeout
    )
    return result
""")
    func = next(
        n
        for n in iox.ast.walk(tree)
        if isinstance(n, iox.ast.FunctionDef) and n.name == "run_java_class"
    )
    module_path_exprs = {
        stmt.targets[0].id: stmt.value
        for stmt in tree.body
        if isinstance(stmt, iox.ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], iox.ast.Name)
    }
    base, _suffix = iox._extract_wrapper_base_argv(func, {}, module_path_exprs, set())
    assert base == ["java", "-cp", "executable"]


def test_extract_wrapper_base_argv_declines_when_fixed_element_follows_param():
    """Conservative guard: a fixed literal AFTER the own-param reference breaks the
    additive this_base + pos_strs model -- must stay unresolved, never guess."""
    tree = iox.ast.parse("""
import subprocess

def run_thing(classname):
    return subprocess.run(["java", classname, "--strict"], capture_output=True)
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    assert iox._extract_wrapper_base_argv(func, {}, {}, set()) == (None, None)


def test_extract_file_resolves_run_java_class_end_to_end(tmp_path):
    src = """
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent.parent
EXECUTABLE = WORKSPACE / "executable"

def run_java_class(classname, timeout=10):
    result = subprocess.run(
        ["java", "-cp", str(EXECUTABLE), classname],
        capture_output=True, text=True, timeout=timeout
    )
    return result

def test_string_utils_main():
    result = run_java_class("org.stathissideris.ascii2image.text.StringUtils")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == [
        "java",
        "-cp",
        "executable",
        "org.stathissideris.ascii2image.text.StringUtils",
    ]
