"""Test for fix 45 (2026-07-17): a TEST-LOCAL variable assigned from a real, on-disk
resolver-resolvable path expression (`input_file = RESOURCES / "simple_box.txt"`),
referenced BARE later at the call site -- the biggest single-tool win of the whole
session. Found via ditaa's `run_ditaa` fixture-factory wrapper (499 call sites, ~90%
of the tool's own tests):

    RESOURCES = Path(__file__).parent.parent / "test_resources" / "test_rendering"

    def test_no_shadows_flag_accepted(run_ditaa, temp_dir):
        input_file = RESOURCES / "simple_box.txt"
        output_file = temp_dir / "out.png"
        result = run_ditaa(input_file, output_file, extra_args=["-S"])

A THIRD variant of the gap fixes 22/28 already closed for two other scopes: fix 22
covers a FIXTURE's return value, fix 28 covers a bare MODULE-level constant referenced
complete or as an inline further-divided base (`str(RESOURCES / 'x')`) -- this covers
a plain local Assign inside the TEST body itself, referenced bare (not `str(...)`
-wrapped, not inline at the call site) later on.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_track_resource_path_vars_resolves_real_file(tmp_path):
    resources = tmp_path / "test_resources"
    resources.mkdir()
    (resources / "simple_box.txt").write_text("+--+\n|  |\n+--+\n", encoding="utf-8", newline="")

    test_file = tmp_path / "test_x.py"
    test_file.write_text("", encoding="utf-8")
    resolver = iox._PathResolver(test_file)

    tree = iox.ast.parse(f"""
from pathlib import Path
RESOURCES = Path({str(tmp_path)!r}) / "test_resources"

def test_x():
    input_file = RESOURCES / "simple_box.txt"
""")
    resolver.learn(tree)
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._track_resource_path_vars(func, resolver)
    assert "input_file" in result
    basename, content = result["input_file"]
    assert basename == "simple_box.txt"
    assert content == "+--+\n|  |\n+--+\n"


def test_track_resource_path_vars_declines_nonexistent_file(tmp_path):
    test_file = tmp_path / "test_x.py"
    test_file.write_text("", encoding="utf-8")
    resolver = iox._PathResolver(test_file)
    tree = iox.ast.parse(f"""
from pathlib import Path
RESOURCES = Path({str(tmp_path)!r}) / "test_resources"

def test_x():
    input_file = RESOURCES / "does_not_exist.txt"
""")
    resolver.learn(tree)
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._track_resource_path_vars(func, resolver)
    assert result == {}


def test_track_resource_path_vars_declines_scratch_output_that_does_not_exist_yet(tmp_path):
    """A scratch OUTPUT path (`temp_dir / 'out.png'`) doesn't exist on disk until the
    real invocation creates it -- must never be mistaken for a real shipped file."""
    test_file = tmp_path / "test_x.py"
    test_file.write_text("", encoding="utf-8")
    resolver = iox._PathResolver(test_file)
    tree = iox.ast.parse("""
def test_x(temp_dir):
    output_file = temp_dir / "out.png"
""")
    resolver.learn(tree)
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._track_resource_path_vars(func, resolver)
    assert result == {}


def test_extract_file_resolves_ditaa_shaped_local_resource_var_end_to_end(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    resources_dir = tests_dir.parent / "test_resources" / "test_rendering"
    resources_dir.mkdir(parents=True)
    (resources_dir / "simple_box.txt").write_text(
        "+--+\n|  |\n+--+\n", encoding="utf-8", newline=""
    )

    conf = tests_dir / "conftest.py"
    conf.write_text(
        """
import subprocess
import tempfile
import pytest
from pathlib import Path

EXECUTABLE = str(Path(__file__).parent / "executable")

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def run_ditaa(temp_dir):
    def _run(input_file, output_file=None, extra_args=None, check=False):
        args = [str(EXECUTABLE)]
        args.append(str(input_file))
        if output_file:
            args.append(str(output_file))
        if extra_args:
            args.extend(extra_args)
        return subprocess.run(args, capture_output=True, text=True, timeout=30)
    return _run
""",
        encoding="utf-8",
    )
    src = """
from pathlib import Path

RESOURCES = Path(__file__).parent.parent / "test_resources" / "test_rendering"

def test_no_shadows_flag_accepted(run_ditaa, temp_dir):
    input_file = RESOURCES / "simple_box.txt"
    output_file = temp_dir / "out.png"
    result = run_ditaa(input_file, output_file, extra_args=["-S"])
    assert result.returncode == 0
"""
    f = tests_dir / "test_x.py"
    f.write_text(src, encoding="utf-8")

    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "simple_box.txt", "out.png", "-S"]
    assert e.files == {"simple_box.txt": "+--+\n|  |\n+--+\n"}
