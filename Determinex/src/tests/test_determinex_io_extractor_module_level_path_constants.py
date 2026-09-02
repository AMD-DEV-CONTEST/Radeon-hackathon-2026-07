"""Test for fix 28 (2026-07-17): bare MODULE-LEVEL path constants (not behind a
fixture) referenced directly via str(NAME) at a call site.

Root-caused via sox's test_util_coverage.py:

    MONKEY_WAV = Path(__file__).parent.parent.parent / "src" / "monkey.wav"

    def test_enum_option_exact_match(run_binary):
        result = run_binary([str(MONKEY_WAV), "-b", "8", ...])

Distinct from the ubiquitous `RESOURCES = Path(...) / "test_resources" / ...`
convention (RESOURCES is always a BASE further divided at the call site, e.g.
`str(RESOURCES / "input.mp4")`, already covered by the resolver's BinOp handling) --
MONKEY_WAV is the COMPLETE file reference, used bare. _file_arg's str(Name)/bare-Name
branch only ever checks files_map and hard-returns None on a miss for any name that
isn't a fixture -- this was invisible without a dedicated eager-resolution pass,
mirroring fix 22's fixture-returned-path reasoning but for module-level constants.

Fixed with _track_module_level_path_exprs (mirrors _track_fixture_real_file_paths,
scoped to module-level ast.Assign instead of fixture bodies), merged into the same
eager-resolution dict extract_file already builds for fixture-returned paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_track_module_level_path_exprs_finds_bare_constant():
    tree = iox.ast.parse("""
from pathlib import Path
MONKEY_WAV = Path(__file__).parent.parent.parent / "src" / "monkey.wav"
""")
    exprs = iox._track_module_level_path_exprs(tree)
    assert "MONKEY_WAV" in exprs
    assert isinstance(exprs["MONKEY_WAV"], iox.ast.BinOp)


def test_track_module_level_path_exprs_excludes_executable_shaped_constant():
    tree = iox.ast.parse("""
from pathlib import Path
EXECUTABLE = Path(__file__).parent.parent.parent / "executable"
""")
    assert iox._track_module_level_path_exprs(tree) == {}


def test_extract_file_resolves_bare_module_constant_end_to_end(tmp_path):
    resources = tmp_path / "src"
    resources.mkdir()
    (resources / "monkey.wav").write_bytes(b"RIFF....WAVEfmt ")
    tests_dir = tmp_path / "eval" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "conftest.py").write_text(
        """
import subprocess
import pytest
from pathlib import Path

@pytest.fixture
def run_binary():
    def _run(args):
        binary = Path(__file__).parent.parent.parent / "executable"
        return subprocess.run([str(binary)] + args, capture_output=True)
    return _run
""",
        encoding="utf-8",
    )
    src = """
from pathlib import Path
MONKEY_WAV = Path(__file__).parent.parent.parent / "src" / "monkey.wav"

def test_enum_option(run_binary):
    result = run_binary([str(MONKEY_WAV), "-b", "8", "/tmp/test_dither.wav"])
    assert result.returncode == 0
"""
    f = tests_dir / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "monkey.wav", "-b", "8", "/tmp/test_dither.wav"]
    assert e.files == {"monkey.wav": "RIFF....WAVEfmt "}
