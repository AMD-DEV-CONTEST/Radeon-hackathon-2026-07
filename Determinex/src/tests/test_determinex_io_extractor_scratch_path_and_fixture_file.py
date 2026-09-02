"""Tests for two fixes (2026-07-17) built to resolve a corpus-wide REGRESSION
discovered right after fixes 19+20 (chained-wrapper discovery, module-level
constants) shipped: a full 201-tool re-scan showed skip rate JUMPING from 18.9%
(fix 18) to 36.9% -- 71 tools regressed, some catastrophically (gromacs -863
examples, ffmpeg -827, sox -654).

Root cause: fix 19's `unresolvable_list_seen` extension (added to correctly abort a
candidate when a positional arg exists but can't be resolved, rather than silently
falling back to a this_base-only guess) started firing MUCH more often once fixes 15-20
gave many more wrappers a learned base -- any positional arg of a type not yet handled
(a bare Name that isn't in vars_map, a Call that isn't a recognized file/fixture
reference) now correctly aborts instead of being silently skipped mid-loop. This
EXPOSED (not created) two whole categories of previously-silently-dropped positional
args that had never had real resolution mechanisms built for them:

Fix A -- INLINE SCRATCH/OUTPUT PATHS: `str(tmp_path / "angle_dist.xvg")` used directly
as a positional arg (an OUTPUT path the tool creates itself, not real input needing
content) -- found via gromacs's whole `run_gmx(..., "-od", str(tmp_path / "x.xvg"),
...)` family. _track_scratch_path_fixtures already covers this exact reasoning for a
SEPARATE fixture that returns such a path; this generalizes it to the same expression
written INLINE at the call site. Real A/B: gromacs 434/1351(skip 917)->789/1351(skip
562).

Fix B -- FIXTURES RETURNING A REAL (non-executable) FILE PATH: `str(monkey_wav)` where
`monkey_wav` is a fixture (`return Path(__file__).parent... / "src" / "monkey.wav"`),
found via sox's whole test_cli_options.py family. Resolved by eagerly evaluating each
such fixture's path expression once per file (via the same _PathResolver.resolve_file_arg
RESOURCES-path resolution already uses) and merging the result directly into files_map,
rather than threading a new parameter through _resolve_list/_resolve_list_concat/
_find_run_call.

Both are genuine net-positive corrections (confidently-wrong examples silently missing
an argument, previously counted as "resolved", now either correctly resolved with the
real value or correctly left skipped) -- not reverts of fixes 19/20, which stay in
place and are independently tested elsewhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402

# ---------- fix A: inline scratch/output paths ----------


def test_file_arg_resolves_inline_tmp_path_scratch_output():
    node = iox.ast.parse('str(tmp_path / "angle_dist.xvg")').body[0].value
    result = iox._file_arg(node, files_map={})
    assert result == ("angle_dist.xvg", "angle_dist.xvg", "")


def test_file_arg_resolves_inline_tmpdir_scratch_output():
    node = iox.ast.parse('str(tmpdir / "out.wav")').body[0].value
    result = iox._file_arg(node, files_map={})
    assert result == ("out.wav", "out.wav", "")


def test_file_arg_does_not_treat_resources_path_as_scratch():
    """A RESOURCES-based path must never be misrouted through the scratch-path
    branch -- it needs the real disk content (resolver.resolve_file_arg's job), not an
    empty placeholder."""
    node = iox.ast.parse('str(RESOURCES / "golden.txt")').body[0].value
    result = iox._file_arg(node, files_map={})
    assert result is None  # no resolver passed -- correctly unresolved, not "" content


def test_extract_file_resolves_multi_arg_call_with_scratch_output(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess

def run_gmx():
    def _run(subcommand=None, *args):
        cmd = ["executable"]
        if subcommand:
            cmd.append(subcommand)
        cmd.extend(args)
        return subprocess.run(cmd, capture_output=True)
    return _run
""",
        encoding="utf-8",
    )
    src = """
def test_angle(run_gmx, tmp_path):
    result = run_gmx("angle", "-od", str(tmp_path / "angle_dist.xvg"))
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "angle", "-od", "angle_dist.xvg"]


def test_control_flow_argv_regression_still_stays_unresolved(tmp_path):
    """The original fix-19-introduced regression this session already caught and fixed
    stays fixed: a control-flow-built argv must never resolve via the scratch-path
    branch or anywhere else -- confirms fix A didn't reopen that hole."""
    src = """
import subprocess

def run_command(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

def test_conditional(flag_value):
    args = [flag_value, "-c", "test"]
    if not flag_value.startswith("--output"):
        args.extend(["-o", "test.png"])
    result = run_command(args)
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 0


# ---------- fix B: fixtures returning a real (non-executable) file path ----------


def test_track_fixture_real_file_paths_finds_path_expression():
    tree = iox.ast.parse("""
import pytest
from pathlib import Path

@pytest.fixture
def monkey_wav():
    return Path(__file__).parent.parent.parent / "src" / "monkey.wav"
""")
    exprs = iox._track_fixture_real_file_paths(tree)
    assert "monkey_wav" in exprs
    assert isinstance(exprs["monkey_wav"], iox.ast.BinOp)


def test_track_fixture_real_file_paths_excludes_executable_shaped_fixtures():
    """A fixture whose path ends in 'executable' belongs to the executable-fixture
    mechanism (_fixture_return_const/_track_fixtures), not this one -- must not be
    double-counted here."""
    tree = iox.ast.parse("""
import pytest
from pathlib import Path

@pytest.fixture
def sox_binary():
    return Path(__file__).parent.parent.parent / "executable"
""")
    assert iox._track_fixture_real_file_paths(tree) == {}


def test_extract_file_resolves_fixture_bound_real_file_end_to_end(tmp_path):
    resources = tmp_path / "src"
    resources.mkdir()
    (resources / "monkey.wav").write_bytes(b"RIFF....WAVEfmt ")
    tests_dir = tmp_path / "eval" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "conftest.py").write_text(
        """
import pytest
import subprocess
from pathlib import Path

@pytest.fixture
def sox_binary():
    return Path(__file__).parent.parent.parent / "executable"

@pytest.fixture
def monkey_wav():
    return Path(__file__).parent.parent.parent / "src" / "monkey.wav"

@pytest.fixture
def run_sox(sox_binary):
    def _run(*args):
        cmd = [str(sox_binary)] + list(args)
        return subprocess.run(cmd, capture_output=True)
    return _run
""",
        encoding="utf-8",
    )
    src = """
def test_rate_option_invalid(run_sox, monkey_wav):
    result = run_sox("-r", "invalid", str(monkey_wav), "/tmp/out.wav")
    assert result.returncode != 0
"""
    f = tests_dir / "test_cli_options.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "-r", "invalid", "monkey.wav", "/tmp/out.wav"]
    assert e.files == {"monkey.wav": "RIFF....WAVEfmt "}
