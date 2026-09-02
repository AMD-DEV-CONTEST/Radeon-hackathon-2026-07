"""Test for fix 36 (2026-07-17): a TEMP-FILES OBJECT fixture -- a custom class
wrapping a real tempfile.mkdtemp() scratch directory, exposing `.create(name,
content)` (stage a real file) and `.path(name="")` (resolve a path inside the
scratch dir, or the dir itself when name is omitted).

Root-caused via dust's whole test suite (278 occurrences of `temp_files.*` in ONE
tool's tests; the identical class shape also confirmed in caps-log, samtools, htop,
and gdal's conftest.py files this same session):

    @pytest.fixture
    def temp_files():
        tempdir = tempfile.mkdtemp()
        class TempFiles:
            def create(self, name, content=""): ...
            def path(self, name=""): ...
        yield TempFiles(tempdir)
        shutil.rmtree(tempdir, ignore_errors=True)

    def test_filecount_flag(temp_files):
        temp_files.create("dir/file1.txt", "x" * 1000)
        result = run("-P", "-c", "-f", str(temp_files.path()))

Neither `.create()` (a real content-staging METHOD CALL, not a Path.write_text())
nor `.path()` (used bare, no name, resolving to the scratch root itself) had any
resolution mechanism at all -- a wholly distinct fixture shape from the existing
custom-scratch-DIR fixtures (yield the bare directory) and temp-file-FACTORY
fixtures (yield a callable producing one fresh file per call).

Also exercises fix 36's companion: _const() gaining ast.BinOp(Mult) support for
string-repetition content (`"x" * 10000`), a common test-data-generation idiom that
was previously entirely unresolvable (_UNK).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_const_resolves_string_repetition():
    node = iox.ast.parse('"x" * 1000').body[0].value
    assert iox._const(node) == "x" * 1000


def test_const_resolves_string_repetition_reversed_operands():
    node = iox.ast.parse('5 * "ab"').body[0].value
    assert iox._const(node) == "ababababab"


def test_const_declines_non_string_mult():
    node = iox.ast.parse("3 * 4").body[0].value
    assert iox._const(node) is iox._UNK


def test_discover_temp_files_object_fixtures_finds_mkdtemp_plus_create_class():
    tree = iox.ast.parse("""
import tempfile
import pytest
from pathlib import Path

@pytest.fixture
def temp_files():
    tempdir = tempfile.mkdtemp()
    class TempFiles:
        def create(self, name, content=""):
            pass
        def path(self, name=""):
            pass
    yield TempFiles()
""")
    assert iox._discover_temp_files_object_fixtures(tree) == {"temp_files"}


def test_discover_temp_files_object_fixtures_ignores_bare_scratch_dir_fixture():
    """A fixture yielding the bare TemporaryDirectory path (fix 23's shape) must
    NOT be mistaken for the object-fixture shape -- no nested class at all here."""
    tree = iox.ast.parse("""
import tempfile
import pytest
from pathlib import Path

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
""")
    assert iox._discover_temp_files_object_fixtures(tree) == set()


def test_track_temp_files_object_creates_resolves_name_and_repeated_content():
    tree = iox.ast.parse("""
def test_x(temp_files):
    temp_files.create("dir/file1.txt", "x" * 1000)
    temp_files.create("file2.txt", "content")
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._track_temp_files_object_creates(func, {"temp_files"}, {})
    assert result == {
        "dir/file1.txt": ("dir/file1.txt", "x" * 1000),
        "file2.txt": ("file2.txt", "content"),
    }


def test_extract_file_resolves_dust_shaped_temp_files_object_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import os
import tempfile
import shutil
import pytest
from pathlib import Path

EXECUTABLE = "./executable"

def run(*args, stdin=None, env=None, cwd=None, timeout=5.0, check=False):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    result = subprocess.run(
        [EXECUTABLE, *args],
        input=stdin.encode() if isinstance(stdin, str) else stdin,
        capture_output=True, timeout=timeout, env=full_env, cwd=cwd,
    )
    return result

@pytest.fixture
def temp_files():
    tempdir = tempfile.mkdtemp()
    class TempFiles:
        def __init__(self, directory):
            self.tempdir = directory
        def create(self, name, content=""):
            path = Path(self.tempdir) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return path
        def path(self, name=""):
            if name:
                return Path(self.tempdir) / name
            return Path(self.tempdir)
    temp = TempFiles(tempdir)
    yield temp
    shutil.rmtree(tempdir, ignore_errors=True)
""",
        encoding="utf-8",
    )
    src = """
def test_filecount_flag(temp_files):
    temp_files.create("dir/file1.txt", "x" * 1000)
    temp_files.create("dir/file2.txt", "x" * 2000)
    result = run("-P", "-c", "-f", str(temp_files.path()))
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "-P", "-c", "-f", "."]
    assert e.files == {
        "dir/file1.txt": "x" * 1000,
        "dir/file2.txt": "x" * 2000,
    }


def test_extract_file_resolves_temp_files_path_with_name_argument(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import tempfile
import shutil
import pytest
from pathlib import Path

EXECUTABLE = "./executable"

def run(*args):
    return subprocess.run(["./executable"] + list(args), capture_output=True)

@pytest.fixture
def temp_files():
    tempdir = tempfile.mkdtemp()
    class TempFiles:
        def create(self, name, content=""):
            path = Path(tempdir) / name
            path.write_text(content)
            return path
        def path(self, name=""):
            return Path(tempdir) / name if name else Path(tempdir)
    yield TempFiles()
    shutil.rmtree(tempdir, ignore_errors=True)
""",
        encoding="utf-8",
    )
    src = """
def test_subdir(temp_files):
    temp_files.create("dir1/a.txt", "hello")
    result = run(str(temp_files.path("dir1")))
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    # "executable" placeholder now correctly resolved (fix 40, 2026-07-17):
    # _is_executable_path_expr now also recognizes a bare string literal with
    # slashes baked in ("./executable"), not just a BinOp/Div chain -- the
    # earlier note here (that this was a separate, unrelated gap) is now stale.
    assert cov.examples[0].argv == ["executable", "dir1"]
