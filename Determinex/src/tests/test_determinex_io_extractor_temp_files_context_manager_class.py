"""Test for fix 37 (2026-07-17): the SAME temp-files-object API (`.create(name,
content)` / `.path(name)`) as fix 36, but bound via a CONTEXT MANAGER
(`with ClassName() as var:`) directly inside a test's own body -- not a pytest
fixture parameter at all.

Root-caused via gdal (159/603 examples, still low after fixes 34-36 -- 355
occurrences across 44 test files):

    class TempFiles:
        def __enter__(self):
            self.tempdir = tempfile.mkdtemp()
            return self
        def __exit__(self, *args):
            shutil.rmtree(self.tempdir, ignore_errors=True)
        def create(self, name, content): ...
        def path(self, name): ...

    def test_dataset_copy():
        with TempFiles() as tf:
            dst = str(tf.path("copy.tif"))
            result = run("dataset", "copy", BYTE_TIF, dst)

Fix 36's temp_files_object_names is derived from FIXTURE discovery
(_discover_temp_files_object_fixtures), so a bare `with TempFiles() as tf:` inside
a test body was entirely invisible -- `tf` is a per-test LOCAL variable, not a
tool-wide fixture parameter. Also: the `.path()` result is assigned to a local var
FIRST (`dst = str(tf.path("copy.tif"))`), then referenced bare later -- fix 36's
_file_arg handling only recognized the call written DIRECTLY at the argv site.

Fixed with two new pieces: _discover_temp_files_context_manager_classes (finds
module-level classes with __enter__ + create methods) +
_track_with_block_scratch_objects (finds `with ClassName() as var:` inside a
test's own body, per-test since the bound name isn't tool-wide) merged with
temp_files_object_names for that test's own resolution; and
_track_temp_files_path_vars (maps a local var assigned from `.path(name)` to that
literal basename, mirroring _track_local_scratch_vars's one-assignment-removed
reasoning).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_discover_temp_files_context_manager_classes_finds_enter_plus_create():
    tree = iox.ast.parse("""
import tempfile
import shutil
from pathlib import Path

class TempFiles:
    def __enter__(self):
        self.tempdir = tempfile.mkdtemp()
        return self
    def __exit__(self, *args):
        shutil.rmtree(self.tempdir, ignore_errors=True)
    def create(self, name, content):
        pass
    def path(self, name):
        pass
""")
    assert iox._discover_temp_files_context_manager_classes(tree) == {"TempFiles"}


def test_discover_temp_files_context_manager_classes_ignores_unrelated_class():
    tree = iox.ast.parse("""
class Helper:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
""")
    assert iox._discover_temp_files_context_manager_classes(tree) == set()


def test_track_with_block_scratch_objects_finds_bound_variable():
    tree = iox.ast.parse("""
def test_x():
    with TempFiles() as tf:
        pass
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    assert iox._track_with_block_scratch_objects(func, {"TempFiles"}) == {"tf"}


def test_track_temp_files_path_vars_resolves_str_wrapped_assignment():
    tree = iox.ast.parse("""
def test_x(tf):
    dst = str(tf.path("copy.tif"))
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    assert iox._track_temp_files_path_vars(func, {"tf"}) == {"dst": "copy.tif"}


def test_extract_file_resolves_gdal_shaped_with_block_end_to_end(tmp_path):
    src = """
import subprocess
import os
import tempfile
import shutil
from pathlib import Path

EXECUTABLE = "./executable"
BYTE_TIF = "/data/byte.tif"

def run(*args, timeout=5.0):
    return subprocess.run([EXECUTABLE, *args], capture_output=True, timeout=timeout)

class TempFiles:
    def __enter__(self):
        self.tempdir = tempfile.mkdtemp()
        return self
    def __exit__(self, *args):
        shutil.rmtree(self.tempdir, ignore_errors=True)
    def create(self, name, content):
        path = Path(self.tempdir) / name
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return path
    def path(self, name):
        return Path(self.tempdir) / name

def test_dataset_copy():
    with TempFiles() as tf:
        dst = str(tf.path("copy.tif"))
        result = run("dataset", "copy", BYTE_TIF, dst)
        assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "dataset", "copy", "/data/byte.tif", "copy.tif"]
