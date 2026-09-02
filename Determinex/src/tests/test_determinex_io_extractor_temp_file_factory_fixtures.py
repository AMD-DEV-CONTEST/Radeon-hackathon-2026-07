"""Test for fix 25 (2026-07-17): temp-file-FACTORY fixtures (`tempfile.mkstemp`-based),
the second fix built after fix 24 (str-wrapped scratch var) to close ffmpeg's and sox's
remaining under-recovery from the fix19/20 regression.

Root-caused via sox (161/1009 examples pre-fix, ~84% skip -- the worst-recovered tool
from fixes 21-23). sox's whole test suite (1320 occurrences across 21 test files) uses
one dominant idiom completely distinct from tmp_path/tmpdir or the custom
TemporaryDirectory-based scratch-DIR fixtures fix 23 already covers:

    @pytest.fixture
    def temp_audio_file():
        files = []
        def _temp_file(suffix=".wav"):
            fd, path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            files.append(path)
            return path
        yield _temp_file
        for f in files: os.unlink(f)

    def test_reverb_default_parameters(run_sox, temp_audio_file):
        input_file = temp_audio_file(".wav")
        ...
        output_file = temp_audio_file(".wav")
        result = run_sox(input_file, output_file, "reverb")

`temp_audio_file` is a fixture returning a CALLABLE FACTORY (not a directory to divide
with `/`) -- each CALL produces a fresh, genuinely distinct real file via
tempfile.mkstemp. Two calls in the same test (input_file, output_file) must map to TWO
DIFFERENT basenames, never collide.

Fixed with _discover_temp_file_factory_fixtures (finds fixture names whose body calls
tempfile.mkstemp) + _track_temp_file_factory_vars (maps each local-var-assigned CALL to
such a fixture to its own `scratch_N{suffix}` basename, N a per-function counter).
Resolved via the ordinary vars_map bare-Name lookup already in place -- no new
_file_arg wiring needed since the values (bare Name, no str() wrap in sox's own tests)
already flow through _resolve()'s existing Name-in-vmap branch.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_discover_temp_file_factory_fixtures_finds_mkstemp_based_fixture():
    tree = iox.ast.parse("""
import tempfile
import os
import pytest

@pytest.fixture
def temp_audio_file():
    files = []
    def _temp_file(suffix=".wav"):
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        files.append(path)
        return path
    yield _temp_file
""")
    assert iox._discover_temp_file_factory_fixtures(tree) == {"temp_audio_file"}


def test_discover_temp_file_factory_fixtures_ignores_non_mkstemp_fixtures():
    tree = iox.ast.parse("""
import pytest

@pytest.fixture
def some_other_fixture():
    return 42
""")
    assert iox._discover_temp_file_factory_fixtures(tree) == set()


def test_track_temp_file_factory_vars_assigns_distinct_basenames_per_call():
    tree = iox.ast.parse("""
def test_x(run_sox, temp_audio_file):
    input_file = temp_audio_file(".wav")
    output_file = temp_audio_file(".wav")
    run_sox(input_file, output_file, "reverb")
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._track_temp_file_factory_vars(func, {"temp_audio_file"})
    assert result == {"input_file": "scratch_0.wav", "output_file": "scratch_1.wav"}
    assert result["input_file"] != result["output_file"]


def test_track_temp_file_factory_vars_ignores_unknown_factory():
    tree = iox.ast.parse("""
def test_x():
    golden_file = some_other_call(".wav")
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    assert iox._track_temp_file_factory_vars(func, {"temp_audio_file"}) == {}


def test_extract_file_resolves_two_distinct_calls_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import tempfile
import os
import pytest

@pytest.fixture
def sox_binary():
    return "executable"

@pytest.fixture
def run_sox(sox_binary):
    def _run(*args):
        cmd = [sox_binary] + list(args)
        return subprocess.run(cmd, capture_output=True)
    return _run

@pytest.fixture
def temp_audio_file():
    files = []
    def _temp_file(suffix=".wav"):
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        files.append(path)
        return path
    yield _temp_file
""",
        encoding="utf-8",
    )
    src = """
def test_reverb(run_sox, temp_audio_file):
    input_file = temp_audio_file(".wav")
    output_file = temp_audio_file(".wav")
    result = run_sox(input_file, output_file, "reverb")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    argv = cov.examples[0].argv
    assert argv[0] == "executable"
    assert argv[1] != argv[2]  # input_file and output_file must be distinct
    assert argv[1] == "scratch_0.wav"
    assert argv[2] == "scratch_1.wav"
    assert argv[3] == "reverb"
