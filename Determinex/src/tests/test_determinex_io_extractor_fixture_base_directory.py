"""Test for fix 46 (2026-07-18): a @pytest.fixture returning a BASE DIRECTORY (not a
single file), further divided AT THE CALL SITE. Found via scc's whole test suite:

    @pytest.fixture
    def examples_dir():
        return Path(__file__).parent.parent.parent / "examples"

    def test_format_json_produces_valid_json_array(run_scc, examples_dir):
        result = run_scc("--format", "json", str(examples_dir / "language" / "go.go"))

Fix 22 (_track_fixture_real_file_paths + resolve_file_arg) already handles a fixture
returning a COMPLETE real file path; that mechanism correctly declines here since
`examples_dir` alone evaluates to a DIRECTORY, not a file (resolve_file_arg requires
.is_file()). The real gap: the resolver's eval_path had no way to resolve a bare Name
rooted at a FIXTURE (only module-level constants populate resolver.vars via learn()),
so `examples_dir / "language" / "go.go"` -- a BinOp/Div chain whose ultimate base is
that fixture Name -- was structurally invisible to eval_path's Name lookup.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_track_fixture_real_file_paths_captures_directory_returning_fixture():
    tree = iox.ast.parse("""
from pathlib import Path
import pytest

@pytest.fixture
def examples_dir():
    return Path(__file__).parent.parent.parent / "examples"
""")
    result = iox._track_fixture_real_file_paths(tree)
    assert "examples_dir" in result


def test_extract_file_resolves_fixture_base_directory_further_divided(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    examples_dir_real = tmp_path / "examples"
    lang_dir = examples_dir_real / "language"
    lang_dir.mkdir(parents=True)
    (lang_dir / "go.go").write_text("package main\n", encoding="utf-8", newline="")

    conf = tests_dir / "conftest.py"
    conf.write_text(
        """
import subprocess
import pytest
from pathlib import Path

EXECUTABLE = str(Path(__file__).parent / "executable")

@pytest.fixture
def binary():
    return Path(__file__).parent.parent / "executable"

@pytest.fixture
def run_scc(binary):
    def _run(*args, input=None, check=False, timeout=30):
        cmd = [str(binary)] + list(args)
        return subprocess.run(cmd, input=input, capture_output=True, text=True, timeout=timeout)
    return _run

@pytest.fixture
def examples_dir():
    return Path(__file__).parent.parent / "examples"
""",
        encoding="utf-8",
    )
    src = """
def test_format_json_produces_valid_json_array(run_scc, examples_dir):
    result = run_scc("--format", "json", str(examples_dir / "language" / "go.go"))
    assert result.returncode == 0
"""
    f = tests_dir / "test_x.py"
    f.write_text(src, encoding="utf-8")

    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "--format", "json", "go.go"]
    assert e.files == {"go.go": "package main\n"}


def test_extract_file_declines_when_subdirectory_file_does_not_exist(tmp_path):
    """The base directory exists but the specific file doesn't -- must not stage a
    fabricated file, must leave the test correctly unresolved."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tmp_path / "examples" / "language").mkdir(parents=True)

    conf = tests_dir / "conftest.py"
    conf.write_text(
        """
import subprocess
import pytest
from pathlib import Path

@pytest.fixture
def binary():
    return Path(__file__).parent.parent.parent / "executable"

@pytest.fixture
def run_scc(binary):
    def _run(*args):
        return subprocess.run([str(binary)] + list(args), capture_output=True, text=True)
    return _run

@pytest.fixture
def examples_dir():
    return Path(__file__).parent.parent.parent / "examples"
""",
        encoding="utf-8",
    )
    src = """
def test_missing(run_scc, examples_dir):
    result = run_scc(str(examples_dir / "language" / "does_not_exist.go"))
    assert result.returncode == 0
"""
    f = tests_dir / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 0
