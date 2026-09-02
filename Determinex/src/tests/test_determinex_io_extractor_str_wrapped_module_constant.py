"""Test for fix 38 (2026-07-17): a module-level path constant assigned via a
str(...)-WRAPPED expression, not a bare BinOp.

Root-caused via gdal's whole conftest.py: `BYTE_TIF = str(REPO_ROOT /
"autotest/gcore/data/byte.tif")` -- str() applied at the ASSIGNMENT itself.
Fix 28's _track_module_level_path_exprs only checked
`isinstance(node.value, ast.BinOp)` directly, which is False for a Call wrapping a
BinOp -- so BYTE_TIF (referenced bare in `run("dataset", "copy", BYTE_TIF, dst)`)
never resolved at all, correctly staying skipped (never a wrong guess, since
_resolve's bare-Name path also has no way to reach it) but recoverable.

Fixed by unwrapping a str(...) call at the assignment level too, before the
existing BinOp/Div check.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_track_module_level_path_exprs_unwraps_str_wrapped_assignment():
    tree = iox.ast.parse("""
from pathlib import Path
REPO_ROOT = Path(__file__).parent.parent.parent
BYTE_TIF = str(REPO_ROOT / "autotest/gcore/data/byte.tif")
""")
    exprs = iox._track_module_level_path_exprs(tree)
    assert "BYTE_TIF" in exprs
    assert isinstance(exprs["BYTE_TIF"], iox.ast.BinOp)


def test_track_module_level_path_exprs_still_resolves_bare_binop():
    """Regression guard: fix 38 must not disturb the original fix-28 bare-BinOp shape."""
    tree = iox.ast.parse("""
from pathlib import Path
MONKEY_WAV = Path(__file__).parent.parent.parent / "src" / "monkey.wav"
""")
    exprs = iox._track_module_level_path_exprs(tree)
    assert "MONKEY_WAV" in exprs


def test_extract_file_resolves_gdal_shaped_str_wrapped_constant_end_to_end(tmp_path):
    resources = tmp_path / "autotest" / "gcore" / "data"
    resources.mkdir(parents=True)
    (resources / "byte.tif").write_text("fake tiff data")
    tests_dir = tmp_path / "eval" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "conftest.py").write_text(
        """
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BYTE_TIF = str(REPO_ROOT / "autotest/gcore/data/byte.tif")
EXECUTABLE = "./executable"

def run(*args):
    return subprocess.run([EXECUTABLE] + list(args), capture_output=True)
""",
        encoding="utf-8",
    )
    src = """
def test_dataset_check():
    result = run("dataset", "info", BYTE_TIF)
    assert result.returncode == 0
"""
    f = tests_dir / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "dataset", "info", "byte.tif"]
    assert e.files == {"byte.tif": "fake tiff data"}
