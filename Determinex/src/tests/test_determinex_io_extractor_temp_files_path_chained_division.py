"""Test for fix 42 (2026-07-17): a temp-files-object `.path()` call FURTHER
DIVIDED by one or more `/ "literal"` segments, optionally chained across
several assignments -- caps-log's whole test suite (635 occurrences):

    with TempFiles() as tf:
        log_dir = tf.path() / "logs"
        year_dir = log_dir / "y2026"
        log_file = year_dir / "d2026_03_25.md"
        config_file = tf.path() / "config.ini"
        result = run("--config", str(config_file), "--log-dir-path", str(log_dir))

Neither the bare no-arg `.path()` (already resolves to ".", fix 36/37) nor a
single division on top of it had any resolution mechanism -- and CHAINING
(a var assigned from one division used as the base of a further division) is
a distinct sub-case, since each division has to resolve against a GROWING
map of previously-resolved vars, not just the immediate `.path()` call.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _capslog_conftest() -> str:
    return """
import subprocess
import tempfile
import shutil
from pathlib import Path

EXECUTABLE = "./executable"

def run(*args):
    return subprocess.run([EXECUTABLE, *args], capture_output=True)

class TempFiles:
    def __enter__(self):
        self.tempdir = tempfile.mkdtemp()
        return self
    def __exit__(self, *args):
        shutil.rmtree(self.tempdir, ignore_errors=True)
    def create(self, name, content=""):
        path = Path(self.tempdir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path
    def path(self, name=""):
        return Path(self.tempdir) / name if name else Path(self.tempdir)
"""


def test_resolve_chain_single_division_from_no_arg_path():
    tree = iox.ast.parse("log_dir = tf.path() / 'logs'")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}) == "logs"


def test_resolve_chain_multi_level_division_single_expr():
    tree = iox.ast.parse("x = tf.path() / 'a' / 'b'")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}) == "a/b"


def test_resolve_chain_declines_unresolvable_rhs():
    tree = iox.ast.parse("x = tf.path() / some_var")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}) is None


def test_resolve_chain_via_prior_resolved_var():
    tree = iox.ast.parse("year_dir = log_dir / 'y2026'")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}, {"log_dir": "logs"}) == "logs/y2026"


def test_resolve_chain_declines_unknown_base_name():
    tree = iox.ast.parse("year_dir = unrelated / 'y2026'")
    node = tree.body[0].value
    assert iox._resolve_temp_files_path_chain(node, {"tf"}, {"log_dir": "logs"}) is None


def test_track_temp_files_path_vars_resolves_multi_level_assignment_chain():
    tree = iox.ast.parse("""
def test_x(tf):
    log_dir = tf.path() / "logs"
    year_dir = log_dir / "y2026"
    log_file = year_dir / "d2026_03_25.md"
    config_file = tf.path() / "config.ini"
""")
    func = next(n for n in iox.ast.walk(tree) if isinstance(n, iox.ast.FunctionDef))
    result = iox._track_temp_files_path_vars(func, {"tf"})
    assert result == {
        "log_dir": "logs",
        "year_dir": "logs/y2026",
        "log_file": "logs/y2026/d2026_03_25.md",
        "config_file": "config.ini",
    }


def test_extract_file_resolves_capslog_shaped_chained_division_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(_capslog_conftest(), encoding="utf-8")
    src = """
from conftest import run, TempFiles

def test_config_with_log_dir():
    with TempFiles() as tf:
        log_dir = tf.path() / "logs"
        log_dir.mkdir()
        config_file = tf.path() / "config.ini"
        config_file.write_text("x")
        result = run("--config", str(config_file), "--log-dir-path", str(log_dir))
        assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == ["executable", "--config", "config.ini", "--log-dir-path", "logs"]


def test_extract_file_resolves_capslog_shaped_multi_level_chain_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(_capslog_conftest(), encoding="utf-8")
    src = """
from conftest import run, TempFiles

def test_encryption_marker_file_content():
    with TempFiles() as tf:
        log_dir = tf.path() / "logs"
        year_dir = log_dir / "y2026"
        year_dir.mkdir(parents=True)
        log_file = year_dir / "d2026_03_25.md"
        log_file.write_text("Test content")
        result = run("--log-dir-path", str(log_dir), "--show-file", str(log_file))
        assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    assert e.argv == [
        "executable",
        "--log-dir-path",
        "logs",
        "--show-file",
        "logs/y2026/d2026_03_25.md",
    ]


def test_file_arg_inline_chained_division_without_intermediate_var(tmp_path):
    """The `_file_arg` inline site (no intermediate variable at all)."""
    conf = tmp_path / "conftest.py"
    conf.write_text(_capslog_conftest(), encoding="utf-8")
    src = """
from conftest import run, TempFiles

def test_inline():
    with TempFiles() as tf:
        result = run("--config", str(tf.path() / "config.ini"))
        assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert cov.examples[0].argv == ["executable", "--config", "config.ini"]
