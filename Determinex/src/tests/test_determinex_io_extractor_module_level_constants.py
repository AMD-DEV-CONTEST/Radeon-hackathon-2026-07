"""Test for module-level constant resolution (2026-07-17), the twentieth fix in the
skip-rate chain. Root-caused via dirble (0/83 resolved, 100% skip -- the only one of
the four near-100%-skip tools from the chained-wrapper investigation with NO conftest.py
at all): its whole test suite calls `subprocess.run([EXECUTABLE, ...])` DIRECTLY in each
test body, no wrapper function or fixture anywhere, where `EXECUTABLE = "../executable"`
is a plain MODULE-LEVEL string constant. None of the existing variable-resolution passes
covered this: _track_vars only walks a single FunctionDef's body (never the module root),
fixtures are @pytest.fixture-decorated functions only, and _PathResolver only tracks
Path-typed module vars for golden-file resolution, not arbitrary string constants used as
plain argv elements.

Fixed by widening _track_vars's accepted type to `ast.FunctionDef | ast.Module` (ast.walk
works identically over either root -- no new constant-tracking logic needed) and calling
it once on the test file's own tree (and conftest.py's, if one exists) in extract_file,
merged into base_vars as the LOWEST-priority layer so it never shadows a same-named
fixture or per-test local variable.

Real A/B: dirble 0/83(skip 83, 100%) -> 15/83(skip 68, 82%). The remaining 68 need a
genuinely separate mechanism (spinning up the test's own http.server.HTTPServer mock
handler as a real local server) -- sized, not built this session.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_track_vars_resolves_module_level_string_constant():
    tree = iox.ast.parse("""
EXECUTABLE = "../executable"

def test_help_output():
    pass
""")
    assert iox._track_vars(tree) == {"EXECUTABLE": "../executable"}


def test_extract_file_resolves_bare_subprocess_call_via_module_constant(tmp_path):
    src = """
import subprocess

EXECUTABLE = "../executable"

def test_help_output():
    result = subprocess.run([EXECUTABLE, "--help"], capture_output=True, text=True)
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["../executable", "--help"]


def test_extract_file_local_var_still_shadows_module_constant(tmp_path):
    """A per-test local of the SAME name must still win -- module constants are the
    lowest-priority layer, never allowed to override a local shadowing it."""
    src = """
import subprocess

EXECUTABLE = "../executable"

def test_uses_local_shadow():
    EXECUTABLE = "./local-override"
    result = subprocess.run([EXECUTABLE, "--help"], capture_output=True, text=True)
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["./local-override", "--help"]


def test_extract_file_resolves_module_constant_defined_in_conftest(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text('EXECUTABLE = "../executable"\n', encoding="utf-8")
    src = """
import subprocess

def test_version_output():
    result = subprocess.run([EXECUTABLE, "--version"], capture_output=True, text=True)
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["../executable", "--version"]
