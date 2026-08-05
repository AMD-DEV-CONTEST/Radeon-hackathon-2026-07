"""Test for fix 39b (2026-07-17): resolver.learn() must process conftest.py BEFORE
the test file itself, so a name collision resolves in the test file's favor.

Root-caused via a REAL corpus-wide regression caught immediately after fix 39
shipped (resolver.learn(conf_tree) added, but in the WRONG order): ditaa's whole
test_svg.py defines its OWN module-level `RESOURCES = Path(__file__).parent.parent
/ "test_resources" / "test_svg"` (a test-file-SPECIFIC subdirectory), while
conftest.py SEPARATELY defines `RESOURCES = WORKSPACE / "test-resources"` (a
different, generic path) for its OWN fixtures' use. Real Python scoping means the
test file's own module-level name is the ONLY one ever visible inside it --
conftest.py's same-named global is a completely separate variable in a different
module's namespace, never merged as a bare name (only pytest FIXTURES cross that
boundary, via explicit dependency injection).

_PathResolver.learn() does a naive dict overwrite with no precedence logic --
calling resolver.learn(conf_tree) AFTER resolver.learn(tree) (fix 39's original,
buggy order) let conftest's WRONG value silently win, breaking resolution for
EVERY test in the file referencing the collided name: test_svg.py's own 30/31
resolved examples (fix 30's real, tested, verified recovery from earlier this same
session) dropped to 12/31 the moment fix 39 shipped. Caught by re-checking every
previously-fixed tool's real numbers after the resolver change, not by trusting
fix 39's own narrow tests alone -- exactly the discipline this whole session is
built on.

Fixed by learning conftest.py FIRST, then the test file itself SECOND, so the test
file's own definitions always win on a name collision.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_test_file_own_constant_wins_over_conftest_name_collision(tmp_path):
    resources_generic = tmp_path / "test-resources"
    resources_generic.mkdir()
    (resources_generic / "simple_box.txt").write_text("WRONG generic content")

    resources_specific = tmp_path / "eval" / "test_resources" / "test_svg"
    resources_specific.mkdir(parents=True)
    (resources_specific / "simple_box.txt").write_text("CORRECT test-specific content")

    tests_dir = tmp_path / "eval" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "conftest.py").write_text(
        """
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent.parent
EXECUTABLE = WORKSPACE / "executable"
RESOURCES = WORKSPACE / "test-resources"

def run_thing(*args):
    return subprocess.run([str(EXECUTABLE), *args], capture_output=True)
""",
        encoding="utf-8",
    )
    src = """
import subprocess
from pathlib import Path

RESOURCES = Path(__file__).parent.parent / "test_resources" / "test_svg"

def test_uses_own_resources(run_thing):
    result = run_thing(RESOURCES / "simple_box.txt")
    assert result.returncode == 0
"""
    f = tests_dir / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "simple_box.txt"]
    # the STAGED content must be the test file's OWN RESOURCES, never conftest's
    # same-named-but-different global.
    assert e.files == {"simple_box.txt": "CORRECT test-specific content"}
