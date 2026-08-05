"""Test for fix 26 (2026-07-17): kwarg PASSTHROUGH in _extract_kwarg_flag_map, the
third fix built for ffmpeg/sox/ditaa's remaining under-recovery from the fix19/20
regression.

Root-caused via ditaa's whole test suite: `run_ditaa`'s own body does
`if extra_args: args.extend(extra_args)` -- the kwarg's own LIST VALUE spliced in
verbatim, not the existing-covered `if <kwname>: cmd.extend([<flag>, <kwname>])` idiom
(duckdb's sql= -> ["-c", sql]). Before this fix, an unrecognized kwarg like extra_args
matched NOTHING in _find_run_call's keyword loop -- there's no abort path for an
unrecognized KEYWORD (only for unresolvable POSITIONAL args via
unresolvable_list_seen), so `run_ditaa(input_file, output_file, extra_args=["-v"])`
resolved SUCCESSFULLY but silently missing "-v" from argv entirely: a confidently
WRONG example, not a skip -- found by hand-reading ditaa's real conftest.py and test
call sites, not by the aggregate recovery count (which can't distinguish a complete
argv from an incomplete one).

Fixed by recognizing the `cmd.extend(kwname)` shape (a bare Name argument matching the
kwarg itself) in _extract_kwarg_flag_map, marking it with the _KWARG_PASSTHROUGH
sentinel, and having _find_run_call's keyword loop splice the kwarg's resolved list
value into pos_strs directly when it sees that marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_extract_kwarg_flag_map_recognizes_passthrough_extend():
    tree = iox.ast.parse("""
def _run(input_file, output_file=None, extra_args=None):
    args = ["executable"]
    args.append(str(input_file))
    if output_file:
        args.append(str(output_file))
    if extra_args:
        args.extend(extra_args)
    return args
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._extract_kwarg_flag_map(func)
    assert result == {"extra_args": iox._KWARG_PASSTHROUGH}


def test_extract_kwarg_flag_map_still_recognizes_fixed_flag_shape():
    """Regression guard: fix 26 must not disturb the existing duckdb-style
    [flag, kwname] 2-element list detection."""
    tree = iox.ast.parse("""
def _run(sql=None):
    cmd = ["executable"]
    if sql:
        cmd.extend(["-c", sql])
    return cmd
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._extract_kwarg_flag_map(func)
    assert result == {"sql": "-c"}


def test_extract_file_resolves_ditaa_shaped_extra_args_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import tempfile
import pytest
from pathlib import Path

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def run_ditaa(temp_dir):
    def _run(input_file, output_file=None, extra_args=None, check=False):
        args = ["executable"]
        args.append(str(input_file))
        if output_file:
            args.append(str(output_file))
        if extra_args:
            args.extend(extra_args)
        return subprocess.run(args, capture_output=True)
    return _run
""",
        encoding="utf-8",
    )
    src = """
def test_svg_output(run_ditaa, temp_dir):
    input_file = temp_dir / "diagram.txt"
    input_file.write_text("+---+")
    output_file = temp_dir / "out.svg"
    result = run_ditaa(input_file, output_file, extra_args=["--svg"])
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "diagram.txt", "out.svg", "--svg"]
