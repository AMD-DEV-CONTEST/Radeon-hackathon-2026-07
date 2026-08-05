"""Test for fix 30 (2026-07-17): a SUFFIX of tokens the wrapper appends AFTER its own
positional-parameter slot -- the biggest remaining architectural gap in ditaa's
recovery (still 117/555 after fixes 21-29, far below the pre-regression 487/555).

Root-caused via ditaa's whole test_svg.py (60+ call sites):

    @pytest.fixture
    def run_ditaa_svg(temp_dir):
        def _run(input_file, extra_args=None):
            output_file = temp_dir / "output.svg"
            args = [str(EXECUTABLE)]
            args.append(str(input_file))
            args.append(str(output_file))
            args.append("--svg")
            if extra_args:
                args.extend(extra_args)
            return subprocess.run(args, ...)
        return _run

    def test_basic_svg_generation(run_ditaa_svg):
        result = run_ditaa_svg(RESOURCES / "simple_box.txt")

`input_file` is the wrapper's OWN parameter -- the existing additive `this_base +
pos_strs` model already handles that slot correctly. But `output_file` (a
wrapper-LOCAL scratch var, `temp_dir / "output.svg"`) and the literal `"--svg"` come
AFTER it -- a SUFFIX the prefix-only base model has no way to represent. Before this
fix, run_ditaa_svg's base was learned as just `["executable"]` with no suffix
concept at all, so the call site's single positional arg became the ENTIRE
remainder of argv: `['executable', 'simple_box.txt']`, silently missing
`output.svg`/`--svg` -- a confidently WRONG example (would run `ditaa
simple_box.txt` with no output path and no --svg flag, an entirely different
invocation than the real test), not a skip.

Fixed by extending _extract_wrapper_base_argv to ALSO scan the wrapper's own
top-level statements (in source order) for `.append()`/`.extend()` calls on the
base's cmd variable AFTER the first reference to one of the wrapper's own
parameters, resolving each via the ordinary exec-ref/constant/vmap path OR (new)
inline scratch-dir-relative resolution (`temp_dir / 'output.svg'`, the same
reasoning `_track_local_scratch_vars` applies to test bodies, applied here to a
wrapper body). The scan stops at the first `if` (fix 26's conditional-flag
territory) or the first unresolvable element -- never guesses a partial suffix.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_extract_wrapper_base_argv_resolves_suffix_after_param():
    tree = iox.ast.parse("""
import subprocess
from pathlib import Path

EXECUTABLE = Path(__file__).parent.parent.parent / "executable"

def _run(input_file, extra_args=None):
    output_file = temp_dir / "output.svg"
    args = [str(EXECUTABLE)]
    args.append(str(input_file))
    args.append(str(output_file))
    args.append("--svg")
    if extra_args:
        args.extend(extra_args)
    return subprocess.run(args, capture_output=True)
""")
    func = next(
        n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef) and n.name == "_run"
    )
    module_path_exprs = {
        stmt.targets[0].id: stmt.value
        for stmt in tree.body
        if isinstance(stmt, iox.ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], iox.ast.Name)
    }
    base, suffix = iox._extract_wrapper_base_argv(
        func, {}, module_path_exprs, set(), {"tmp_path", "tmpdir", "temp_dir"}
    )
    assert base == ["executable"]
    assert suffix == ["output.svg", "--svg"]


def test_extract_wrapper_base_argv_suffix_none_without_scratch_bases():
    """Without temp_dir registered as a scratch base, output_file can't resolve --
    the suffix scan must bail (return None), never guess a partial/wrong suffix."""
    tree = iox.ast.parse("""
import subprocess
from pathlib import Path

EXECUTABLE = Path(__file__).parent.parent.parent / "executable"

def _run(input_file):
    output_file = temp_dir / "output.svg"
    args = [str(EXECUTABLE)]
    args.append(str(input_file))
    args.append(str(output_file))
    return subprocess.run(args, capture_output=True)
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    module_path_exprs = {
        stmt.targets[0].id: stmt.value
        for stmt in tree.body
        if isinstance(stmt, iox.ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], iox.ast.Name)
    }
    base, suffix = iox._extract_wrapper_base_argv(func, {}, module_path_exprs, set(), set())
    assert base == ["executable"]
    assert suffix is None


def test_extract_file_resolves_ditaa_svg_shaped_test_end_to_end(tmp_path):
    resources = tmp_path / "eval" / "test_resources" / "test_svg"
    resources.mkdir(parents=True)
    (resources / "simple_box.txt").write_text("+---+\n|   |\n+---+\n")
    tests_dir = tmp_path / "eval" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "conftest.py").write_text(
        """
import tempfile
import pytest
from pathlib import Path

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
""",
        encoding="utf-8",
    )
    src = """
import subprocess
from pathlib import Path
import pytest

RESOURCES = Path(__file__).parent.parent / "test_resources" / "test_svg"

@pytest.fixture
def run_ditaa_svg(temp_dir):
    def _run(input_file, extra_args=None):
        output_file = temp_dir / "output.svg"
        args = [str(Path(__file__).parent.parent.parent / "executable")]
        args.append(str(input_file))
        args.append(str(output_file))
        args.append("--svg")
        if extra_args:
            args.extend(extra_args)
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return result
    return _run

def test_basic_svg_generation(run_ditaa_svg):
    result = run_ditaa_svg(RESOURCES / "simple_box.txt")
    assert result.returncode == 0
"""
    f = tests_dir / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "simple_box.txt", "output.svg", "--svg"]


def test_extract_file_resolves_ditaa_svg_with_extra_args_end_to_end(tmp_path):
    """The conditional extra_args passthrough (fix 26/27) must still combine
    correctly, appending AFTER the new suffix -- matching the real wrapper's own
    execution order (unconditional appends, then the conditional extend)."""
    resources = tmp_path / "eval" / "test_resources" / "test_svg"
    resources.mkdir(parents=True)
    (resources / "simple_box.txt").write_text("+---+\n|   |\n+---+\n")
    tests_dir = tmp_path / "eval" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "conftest.py").write_text(
        """
import tempfile
import pytest
from pathlib import Path

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
""",
        encoding="utf-8",
    )
    src = """
import subprocess
from pathlib import Path
import pytest

RESOURCES = Path(__file__).parent.parent / "test_resources" / "test_svg"

@pytest.fixture
def run_ditaa_svg(temp_dir):
    def _run(input_file, extra_args=None):
        output_file = temp_dir / "output.svg"
        args = [str(Path(__file__).parent.parent.parent / "executable")]
        args.append(str(input_file))
        args.append(str(output_file))
        args.append("--svg")
        if extra_args:
            args.extend(extra_args)
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return result
    return _run

def test_svg_scaled(run_ditaa_svg):
    result = run_ditaa_svg(RESOURCES / "simple_box.txt", extra_args=["-s", "2.0"])
    assert result.returncode == 0
"""
    f = tests_dir / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == [
        "executable",
        "simple_box.txt",
        "output.svg",
        "--svg",
        "-s",
        "2.0",
    ]
