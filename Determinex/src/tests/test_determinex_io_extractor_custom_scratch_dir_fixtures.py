"""Test for custom-named scratch-directory fixtures (2026-07-17), the third fix built
to close the corpus-wide regression from fixes 19+20 (alongside the inline scratch-path
and fixture-real-file-path fixes in
test_determinex_io_extractor_scratch_path_and_fixture_file.py).

Found via ditaa (487->54 examples after the regression, a near-total collapse): its
whole test suite uses a CUSTOM fixture `temp_dir` --

    @pytest.fixture
    def temp_dir():
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

-- semantically identical scratch-directory reasoning to pytest's own tmp_path/tmpdir
(a fresh, empty, per-test location the tool creates output into), just under an
arbitrary name and built from tempfile.TemporaryDirectory() directly rather than
pytest's fixture. Tests then assign a LOCAL VARIABLE from it and pass that bare (no
str() wrap): `output_file = temp_dir / "output.png"`, then
`run_ditaa(input_file, output_file)`.

Fixed with two pieces: _discover_custom_scratch_dir_fixtures finds fixture names built
from tempfile.TemporaryDirectory() (widening the known scratch-base set beyond the
hardcoded tmp_path/tmpdir), and _track_local_scratch_vars maps a TEST-LOCAL variable
assigned from any known scratch base to its literal basename, merged into vars_map so
the ordinary bare-Name resolution path already picks it up -- no new _file_arg
threading needed.

Real A/B: ditaa 54/555(skip 501)->96/555(skip 459) recovering some but not all --
ditaa's remaining skips need further, not-yet-investigated mechanisms (this session
ran out of time to fully restore it to the pre-regression 487/555 baseline).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_discover_custom_scratch_dir_fixtures_finds_tempfile_based_fixture():
    tree = iox.ast.parse("""
import tempfile
import pytest
from pathlib import Path

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
""")
    assert iox._discover_custom_scratch_dir_fixtures(tree) == {"temp_dir"}


def test_discover_custom_scratch_dir_fixtures_ignores_non_tempfile_fixtures():
    tree = iox.ast.parse("""
import pytest

@pytest.fixture
def some_other_fixture():
    return 42
""")
    assert iox._discover_custom_scratch_dir_fixtures(tree) == set()


def test_track_local_scratch_vars_resolves_assignment_from_custom_base():
    tree = iox.ast.parse("""
def test_x(temp_dir):
    output_file = temp_dir / "output.png"
    run_thing(output_file)
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._track_local_scratch_vars(func, {"temp_dir"})
    assert result == {"output_file": "output.png"}


def test_track_local_scratch_vars_ignores_unknown_base():
    """A base NOT in the known scratch set (e.g. a real RESOURCES path) must never be
    treated as a scratch location."""
    tree = iox.ast.parse("""
def test_x():
    golden_file = RESOURCES / "golden.txt"
    run_thing(golden_file)
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    assert iox._track_local_scratch_vars(func, {"temp_dir", "tmp_path", "tmpdir"}) == {}


def test_extract_file_resolves_bare_local_var_from_custom_scratch_fixture(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import tempfile
import subprocess
import pytest
from pathlib import Path

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def run_ditaa(temp_dir):
    def _run(input_file, output_file=None):
        cmd = ["executable"]
        cmd.append(str(input_file))
        if output_file:
            cmd.append(str(output_file))
        return subprocess.run(cmd, capture_output=True)
    return _run
""",
        encoding="utf-8",
    )
    src = """
def test_basic_png_conversion(run_ditaa, temp_dir):
    output_file = temp_dir / "output.png"
    result = run_ditaa("input.txt", output_file)
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "input.txt", "output.png"]
