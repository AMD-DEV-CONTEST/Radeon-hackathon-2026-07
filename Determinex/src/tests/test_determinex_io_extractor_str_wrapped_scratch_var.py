"""Test for fix 24 (2026-07-17): `str(Name)` wrapping a vars_map-tracked local variable.

Root-caused via ffmpeg (903/1794 examples, ~50% skip -- the largest single remaining
gap after fixes 21-23 closed the fix19/20 regression). ffmpeg's whole test suite follows
one dominant idiom:

    output = tmp_path / "out.mkv"
    result = run_ffmpeg("-i", str(RESOURCES / "in.mp4"), ..., str(output), "-y")

`output` resolves fine into vars_map via _track_local_scratch_vars (fix 23). But the
call site wraps it in `str(...)` (738 occurrences across 26 ffmpeg test files alone),
and NEITHER existing resolution path handled that:

- _file_arg's own `str(Name)` branch only ever checks files_map (never vars_map), and
  hard-returns None the moment that lookup misses -- it never falls through to any
  other mechanism once `target` is set.
- _resolve()'s vmap fallback only unwrapped a BARE ast.Name (`if isinstance(node,
  ast.Name) and node.id in vmap`) -- str(Name) is an ast.Call, not an ast.Name, so this
  branch never fired either.

The net effect: any `str(local_var)` where local_var was tracked into vars_map (whether
via _track_local_scratch_vars's scratch-output reasoning or plain _track_vars's
constant-tracking) silently failed to resolve, correctly aborting the whole candidate
(unresolvable_list_seen) rather than guessing -- correctly SKIPPED, but skippable no
longer than necessary once fixed.

Fixed by mirroring the bare-Name branch in _resolve(): unwrap `str(Name)` and check vmap
for the inner Name, returning `str(vmap[name])`. This is NOT ffmpeg-specific -- it's a
general Python idiom (assign a Path, then str() it for subprocess argv) so the fix
applies via _find_run_call's and _resolve_list's shared _resolve() call.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_resolve_unwraps_str_of_tracked_name():
    node = iox.ast.parse("str(output)").body[0].value
    assert iox._resolve(node, {"output": "out.mkv"}) == "out.mkv"


def test_resolve_str_of_untracked_name_stays_unknown():
    node = iox.ast.parse("str(missing)").body[0].value
    assert iox._resolve(node, {}) is iox._UNK


def test_resolve_bare_name_still_works():
    """Regression guard: fix 24 must not disturb the existing bare-Name vmap lookup."""
    node = iox.ast.parse("output").body[0].value
    assert iox._resolve(node, {"output": "out.mkv"}) == "out.mkv"


def test_extract_file_resolves_variadic_call_with_str_wrapped_scratch_output(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import pytest

@pytest.fixture
def run_ffmpeg():
    def _run(*args, **kwargs):
        cmd = ["executable"] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True)
    return _run
""",
        encoding="utf-8",
    )
    src = """
def test_multistream_mkv(run_ffmpeg, tmp_path):
    output = tmp_path / "out.mkv"
    result = run_ffmpeg("-i", "in.mp4", "-c", "copy", str(output), "-y")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "-i", "in.mp4", "-c", "copy", "out.mkv", "-y"]


def test_extract_file_resolves_list_literal_with_str_wrapped_scratch_output(tmp_path):
    """The same str(Name) fix must also apply inside a LIST-literal argv (_resolve_list
    shares the same _resolve() call), not just the variadic-*args path above."""
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import pytest

@pytest.fixture
def run_thing():
    def _run(args):
        cmd = ["executable"] + args
        return subprocess.run(cmd, capture_output=True, text=True)
    return _run
""",
        encoding="utf-8",
    )
    src = """
def test_output_via_list(run_thing, tmp_path):
    output = tmp_path / "result.bin"
    result = run_thing(["-o", str(output)])
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "-o", "result.bin"]
