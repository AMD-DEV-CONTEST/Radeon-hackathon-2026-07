"""Test for fixes 40-41 (2026-07-17): yj's whole conftest.py (12/299 examples, the
worst-recovering tool sampled this session -- previously documented as "sized but
not built").

Fix 40 -- CANDIDATE-PROBE LOOP: `yj_binary`'s body is a filesystem PROBE at
fixture-resolution time:

    def yj_binary():
        candidates = [Path("../executable"), Path("./executable"),
                      Path(__file__).parent.parent.parent / "executable"]
        for path in candidates:
            resolved = path.resolve()
            if resolved.exists():
                return resolved
        raise FileNotFoundError(...)

Whichever candidate ACTUALLY exists on disk depends on cwd -- unknowable via pure
AST analysis. But every candidate is executable-path-shaped, so regardless of
which one wins at runtime, the semantic answer is always "the executable
placeholder". Also required extending _is_executable_path_expr itself: the first
two candidates (`Path("../executable")`, `Path("./executable")`) are single STRING
LITERALS with slashes baked in, never built via a BinOp/Div chain at all -- the
existing while-loop never even ran for them.

Fix 41 -- SINGLE-VALUE APPEND PASSTHROUGH: `run_yj`'s own body does `if flags:
cmd.append(flags)` -- the kwarg's own STRING value appended directly as ONE argv
token (`run_yj(flags="-h")`), distinct from fix 26's _KWARG_PASSTHROUGH (which
splices a LIST kwarg's elements via `.extend()`). Also added "stdin_data" to
STDIN_KW (yj's `run_yj(flags=..., stdin_data=...)` signature).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_is_executable_path_expr_recognizes_bare_string_literal_with_slash():
    node = iox.ast.parse('Path("../executable")').body[0].value
    assert iox._is_executable_path_expr(node) is True


def test_is_executable_path_expr_declines_unrelated_string_literal():
    node = iox.ast.parse('Path("../data.txt")').body[0].value
    assert iox._is_executable_path_expr(node) is False


def test_fixture_return_const_resolves_candidate_probe_loop():
    tree = iox.ast.parse("""
from pathlib import Path

def yj_binary():
    candidates = [
        Path("../executable"),
        Path("./executable"),
        Path(__file__).parent.parent.parent / "executable",
    ]
    for path in candidates:
        resolved = path.resolve()
        if resolved.exists():
            return resolved
    raise FileNotFoundError("Cannot find yj executable")
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    assert iox._fixture_return_const(func) == "executable"


def test_fixture_return_const_declines_probe_loop_with_non_executable_candidate():
    """Conservative guard: if even ONE candidate isn't executable-shaped, never guess."""
    tree = iox.ast.parse("""
from pathlib import Path

def data_file():
    candidates = [Path("../data.txt"), Path("./data.txt")]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("not found")
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    assert iox._fixture_return_const(func) is None


def test_extract_kwarg_flag_map_recognizes_single_value_append_passthrough():
    tree = iox.ast.parse("""
def _run(flags="", stdin_data=""):
    cmd = ["executable"]
    if flags:
        cmd.append(flags)
    return cmd
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._extract_kwarg_flag_map(func)
    assert result == {"flags": iox._KWARG_APPEND_PASSTHROUGH}


def test_extract_file_resolves_yj_shaped_test_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def yj_binary():
    candidates = [
        Path("../executable"),
        Path("./executable"),
        Path(__file__).parent.parent.parent / "executable",
    ]
    for path in candidates:
        resolved = path.resolve()
        if resolved.exists():
            return resolved
    raise FileNotFoundError("Cannot find yj executable")


@pytest.fixture
def run_yj(yj_binary):
    def _run(flags="", stdin_data=""):
        cmd = [str(yj_binary)]
        if flags:
            cmd.append(flags)
        env = os.environ.copy()
        result = subprocess.run(
            cmd,
            input=stdin_data.encode() if isinstance(stdin_data, str) else stdin_data,
            capture_output=True, timeout=5, env=env,
        )
        return result
    return _run
""",
        encoding="utf-8",
    )
    src = """
def test_help(run_yj):
    result = run_yj(flags="-h")
    assert result.returncode == 0

def test_yaml_to_json(run_yj):
    result = run_yj(flags="-yj", stdin_data="key: value")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 2
    by_name = {e.test: e for e in cov.examples}
    assert by_name["test_help"].argv == ["executable", "-h"]
    assert by_name["test_help"].stdin is None
    assert by_name["test_yaml_to_json"].argv == ["executable", "-yj"]
    assert by_name["test_yaml_to_json"].stdin == "key: value"
