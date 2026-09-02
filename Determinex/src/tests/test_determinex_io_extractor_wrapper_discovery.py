"""Tests for determinex_io_extractor.py's wrapper-name auto-discovery (2026-07-16).

Background: RUN_NAMES was a hardcoded allowlist grown one tool-specific name at a time
(literally includes run_minimap, run_nomino). Audited against the real corpus: 210,040
observed tests, 148,132 (70.5%) silently skipped by extract_file/extract_dir. A real case
(jq) recovered ~20% of its own skips from adding ONE missing name (run_jq) -- and different
jq test-suite branches used run_exe, run_jq, and other names for the identical underlying
subprocess wrapper, proving a static name list can't keep pace across ~200 real tools.

Fixed by resolving BEHAVIOR instead of NAME: _shells_out() + _discover_wrapper_names() find
any locally-defined function (in the test file itself, or a sibling conftest.py/utils.py/
helpers.py/common.py/testutils.py) whose body directly calls subprocess.run/Popen/call/
check_output/check_call or os.system/os.popen, and treat it as an ad-hoc runner for that
directory -- regardless of what it's named. Verified against real corpus data (jq, sqlite)
before writing these tests, not just synthetic cases.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _func(src: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))


# ---------- _shells_out(): direct subprocess/os calls ----------


def test_shells_out_detects_subprocess_run():
    f = _func("def run_jq(args):\n    return subprocess.run([EXE, *args], capture_output=True)")
    assert iox._shells_out(f)


def test_shells_out_detects_subprocess_popen():
    f = _func("def invoke(args):\n    return subprocess.Popen([EXE, *args])")
    assert iox._shells_out(f)


def test_shells_out_detects_subprocess_check_output():
    f = _func("def call_tool(args):\n    return subprocess.check_output([EXE, *args])")
    assert iox._shells_out(f)


def test_shells_out_detects_os_system():
    f = _func("def legacy_run(cmd):\n    return os.system(cmd)")
    assert iox._shells_out(f)


def test_shells_out_detects_sp_alias():
    """A common pattern: `import subprocess as sp`."""
    f = _func("def run_it(args):\n    return sp.run([EXE, *args])")
    assert iox._shells_out(f)


def test_shells_out_detects_wrapper_of_a_wrapper():
    """A function that itself calls an already-known RUN_NAMES entry is also a runner."""
    f = _func("def my_custom_helper(args):\n    return run_exe(*args)")
    assert iox._shells_out(f)


def test_shells_out_false_for_unrelated_function():
    f = _func("def add(a, b):\n    return a + b")
    assert not iox._shells_out(f)


def test_shells_out_false_for_unrelated_dot_run_method():
    """A `.run()` call on something that ISN'T subprocess/sp should not false-positive."""
    f = _func("def do_thing(pipeline):\n    return pipeline.run()")
    assert not iox._shells_out(f)


# ---------- _discover_wrapper_names(): own file + sibling helper modules ----------


def test_discover_wrapper_names_finds_locally_defined_wrapper():
    src = (
        "import subprocess\n"
        "def run_jq(args, stdin_bytes=b''):\n"
        "    return subprocess.run(['jq', *args], input=stdin_bytes, capture_output=True)\n"
        "def test_something():\n"
        "    r = run_jq(['-n', '1+2'])\n"
        "    assert r.returncode == 0\n"
    )
    tree = ast.parse(src)
    names = iox._discover_wrapper_names(tree, Path("test_fake.py"))
    assert "run_jq" in names


def test_discover_wrapper_names_never_flags_test_functions_themselves():
    src = "def test_foo():\n    assert 1 == 1\n"
    tree = ast.parse(src)
    names = iox._discover_wrapper_names(tree, Path("test_fake.py"))
    assert names == set()


def test_discover_wrapper_names_finds_sibling_conftest_wrapper(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "import subprocess\n"
        "def run_exe_custom(*args, stdin=None):\n"
        "    return subprocess.run(['tool', *args], input=stdin, capture_output=True)\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_thing.py"
    test_file.write_text(
        "from conftest import run_exe_custom\n"
        "def test_it():\n"
        "    r = run_exe_custom('--help')\n"
        "    assert r.returncode == 0\n",
        encoding="utf-8",
    )
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    names = iox._discover_wrapper_names(tree, test_file)
    assert "run_exe_custom" in names


def test_discover_wrapper_names_checks_utils_and_helpers_too(tmp_path):
    (tmp_path / "utils.py").write_text(
        "import subprocess\ndef call_binary(a):\n    return subprocess.run(a)\n",
        encoding="utf-8",
    )
    (tmp_path / "helpers.py").write_text(
        "import os\ndef sh(cmd):\n    return os.system(cmd)\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_thing.py"
    test_file.write_text("def test_it():\n    pass\n", encoding="utf-8")
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    names = iox._discover_wrapper_names(tree, test_file)
    assert "call_binary" in names
    assert "sh" in names


def test_discover_wrapper_names_does_not_rescan_itself_as_a_helper(tmp_path):
    """A test file named conftest.py-adjacent shouldn't double-scan itself."""
    test_file = tmp_path / "conftest.py"
    test_file.write_text(
        "import subprocess\ndef run_it(a):\n    return subprocess.run(a)\n",
        encoding="utf-8",
    )
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    names = iox._discover_wrapper_names(tree, test_file)
    assert names == {"run_it"}  # found once, not duplicated/erroring


# ---------- _find_run_call(): extra_run_names actually widens recognition ----------


def test_find_run_call_recognizes_extra_run_name():
    src = "def test_something():\n    r = run_jq(['-n', '1+2'])\n    assert r.returncode == 0\n"
    func = _func(src)
    argv, stdin, env, files = iox._find_run_call(func, extra_run_names={"run_jq"})
    assert argv == ["-n", "1+2"]


def test_find_run_call_without_extra_names_fails_on_unknown_wrapper():
    """Regression guard: confirms the FAILURE MODE this whole fix addresses actually exists
    without extra_run_names -- an unrecognized wrapper name with no extra_run_names hint and
    no stdin/args keyword is NOT resolved."""
    src = "def test_something():\n    r = run_jq(['-n', '1+2'])\n    assert r.returncode == 0\n"
    func = _func(src)
    argv, stdin, env, files = iox._find_run_call(func)
    assert argv is None


# ---------- end-to-end: extract_file() recovers a previously-unresolvable test ----------


def test_extract_file_recovers_custom_named_wrapper_defined_in_same_file(tmp_path):
    test_file = tmp_path / "test_mytool.py"
    test_file.write_text(
        "import subprocess\n"
        "def run_jq(args, stdin_bytes=b''):\n"
        "    return subprocess.run(['jq', *args], input=stdin_bytes, capture_output=True)\n"
        "def test_basic_math():\n"
        "    r = run_jq(['-n', '1+2'])\n"
        "    assert r.returncode == 0\n"
        "    assert r.stdout == b'3\\n'\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    assert cov.skipped == []
    assert cov.examples[0].argv == ["-n", "1+2"]


def test_extract_file_recovers_wrapper_defined_in_sibling_conftest(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "import subprocess\n"
        "def run_exe_custom(*args):\n"
        "    return subprocess.run(['tool', *args], capture_output=True)\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_mytool.py"
    test_file.write_text(
        "from conftest import run_exe_custom\n"
        "def test_help():\n"
        "    r = run_exe_custom('--help')\n"
        "    assert r.returncode == 0\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    assert cov.skipped == []


def test_extract_file_still_skips_genuinely_unresolvable_tests(tmp_path):
    """Not a blanket fix -- a test with no recognizable run call at all (no subprocess
    anywhere, not even indirectly) should still be honestly skipped, not fabricated."""
    test_file = tmp_path / "test_mytool.py"
    test_file.write_text(
        "def test_something_unrelated():\n    assert compute_something() == 42\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 0
    assert cov.skipped == ["test_something_unrelated"]


def test_extract_inputs_file_also_benefits_from_wrapper_discovery(tmp_path):
    test_file = tmp_path / "test_mytool.py"
    test_file.write_text(
        "import subprocess\n"
        "def run_jq(args):\n"
        "    return subprocess.run(['jq', *args], capture_output=True)\n"
        "def test_x():\n"
        "    run_jq(['-n', '.'])\n",
        encoding="utf-8",
    )
    probes = iox.extract_inputs_file(test_file)
    assert len(probes) == 1
    assert probes[0].argv == ["-n", "."]
