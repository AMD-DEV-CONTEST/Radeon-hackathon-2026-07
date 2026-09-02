"""Test for fix 43 (2026-07-17): a temp-files-object exposing its scratch dir as a
bare PUBLIC ATTRIBUTE (`self.tempdir`) rather than a `.path()` method -- a sibling
convention to fix 36/37/42's `.path()`-based class, found via calcurse's whole test
suite (590 occurrences):

    class TempFiles:
        def __init__(self): self.tempdir = None
        def __enter__(self):
            self.tempdir = tempfile.mkdtemp()
            return self
        def __exit__(self, *args):
            shutil.rmtree(self.tempdir, ignore_errors=True)
        def create(self, name, content): ...

    def test_config_firstday_monday():
        with TempFiles() as tf:
            conf_dir = Path(tf.tempdir) / "conf"
            conf_dir.mkdir()
            result = run("-D", tf.tempdir, "-C", str(conf_dir))

Two distinct shapes: `tf.tempdir` used BARE, directly as an argv arg (resolves to
"." -- the scratch root, same as fix 36/37's no-arg `.path()`), and `Path(tf.tempdir)
/ "conf"` -- Path()-wrapped then further divided (resolves via the same suffix-chain
logic fix 42 built for `.path() / "x"`).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _calcurse_conftest() -> str:
    return """
import subprocess
import tempfile
import shutil
from pathlib import Path

EXECUTABLE = "/workspace/executable"

def run(*args):
    return subprocess.run([EXECUTABLE, *args], capture_output=True)

class TempFiles:
    def __init__(self):
        self.tempdir = None
    def __enter__(self):
        self.tempdir = tempfile.mkdtemp()
        return self
    def __exit__(self, *args):
        shutil.rmtree(self.tempdir, ignore_errors=True)
    def create(self, name, content):
        path = Path(self.tempdir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path
"""


def test_resolve_bare_tempdir_attribute():
    tree = iox.ast.parse("tf.tempdir")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}) == "."


def test_resolve_path_wrapped_tempdir_with_division():
    tree = iox.ast.parse("Path(tf.tempdir) / 'conf'")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}) == "conf"


def test_resolve_path_wrapped_tempdir_multi_level_division():
    tree = iox.ast.parse("Path(tf.tempdir) / 'a' / 'b'")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}) == "a/b"


def test_resolve_declines_tempdir_attribute_on_unknown_object():
    tree = iox.ast.parse("Path(other.tempdir) / 'conf'")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}) is None


def test_resolve_declines_unrelated_attribute():
    tree = iox.ast.parse("Path(tf.otherattr) / 'conf'")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}) is None


def test_track_temp_files_path_vars_resolves_path_wrapped_tempdir():
    tree = iox.ast.parse("""
def test_x(tf):
    conf_dir = Path(tf.tempdir) / "conf"
    data_dir = Path(tf.tempdir) / "data"
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._track_temp_files_path_vars(func, {"tf"})
    assert result == {"conf_dir": "conf", "data_dir": "data"}


def test_extract_file_resolves_bare_tempdir_arg_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(_calcurse_conftest(), encoding="utf-8")
    src = """
from conftest import run, TempFiles

def test_bare_tempdir():
    with TempFiles() as tf:
        result = run("-D", tf.tempdir, "-Q", "--read-only")
        assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "-D", ".", "-Q", "--read-only"]


def test_extract_file_resolves_path_wrapped_tempdir_division_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(_calcurse_conftest(), encoding="utf-8")
    src = """
from conftest import run, TempFiles
from pathlib import Path

def test_config_firstday_monday():
    with TempFiles() as tf:
        conf_dir = Path(tf.tempdir) / "conf"
        conf_dir.mkdir()
        data_dir = Path(tf.tempdir) / "data"
        data_dir.mkdir()
        result = run("-C", str(conf_dir), "-D", str(data_dir), "-Q", "--read-only")
        assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "-C", "conf", "-D", "data", "-Q", "--read-only"]
