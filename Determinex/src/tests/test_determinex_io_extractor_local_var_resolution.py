"""Tests for determinex_io_extractor.py's shared local-variable resolution layer
(2026-07-16), the third fix in the skip-rate chain (see test_determinex_io_extractor_
wrapper_discovery.py and test_determinex_io_extractor_assertion_helpers.py for the first two).

_find_run_call has had local-binding resolution for argv/stdin all along (_track_vars).
_find_expectations never shared any of it and only matched DIRECT attribute shapes
(X.returncode, X.stdout). Found via a REAL solar test (`code, out = run_exe(...)`) that
_find_run_call resolved fine (its args don't care how the return value gets used) but
_find_expectations missed entirely -- `code`/`out` are bare Names, not attributes.

Three indirection shapes, all found against real test source before building anything:
  1. Tuple-unpacked wrapper results: `code, out = run_exe(...)`.
  2. Decode-to-local-variable written directly in a TEST body (not just inside an
     assertion helper -- that narrower case was already handled).
  3. A for-loop iteration variable over a literal list used in an `in` check:
     `for needle in [...]: assert needle in out`.
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


# ---------- _analyze_run_wrapper_return_shape(): tuple-return position mapping ----------


def test_analyze_return_shape_rc_then_stdout():
    wrapper = _func(
        "def run_exe(args):\n"
        "    proc = subprocess.run([EXE, *args], capture_output=True)\n"
        "    return proc.returncode, proc.stdout\n"
    )
    shape = iox._analyze_run_wrapper_return_shape(wrapper)
    assert shape == {"rc_pos": 0, "stdout_pos": 1}


def test_analyze_return_shape_stdout_then_rc():
    """Order shouldn't be assumed -- resolve from what each element actually IS."""
    wrapper = _func(
        "def run_exe(args):\n"
        "    proc = subprocess.run([EXE, *args], capture_output=True)\n"
        "    return proc.stdout, proc.returncode\n"
    )
    shape = iox._analyze_run_wrapper_return_shape(wrapper)
    assert shape == {"stdout_pos": 0, "rc_pos": 1}


def test_analyze_return_shape_with_decode_call():
    wrapper = _func(
        "def run_exe(args):\n"
        "    proc = subprocess.run([EXE, *args], capture_output=True)\n"
        '    return proc.returncode, proc.stdout.decode("utf-8")\n'
    )
    shape = iox._analyze_run_wrapper_return_shape(wrapper)
    assert shape["rc_pos"] == 0
    assert shape["stdout_pos"] == 1


def test_analyze_return_shape_three_tuple_with_stderr():
    wrapper = _func(
        "def run_exe(args):\n"
        "    proc = subprocess.run([EXE, *args], capture_output=True)\n"
        "    return proc.returncode, proc.stdout, proc.stderr\n"
    )
    shape = iox._analyze_run_wrapper_return_shape(wrapper)
    assert shape == {"rc_pos": 0, "stdout_pos": 1, "stderr_pos": 2}


def test_analyze_return_shape_single_object_returns_none():
    """A wrapper returning ONE object (not a tuple) already goes through the direct
    attribute-access path -- this function should return None, not a bogus shape."""
    wrapper = _func(
        "def run_exe(args):\n    return subprocess.run([EXE, *args], capture_output=True)\n"
    )
    assert iox._analyze_run_wrapper_return_shape(wrapper) is None


def test_analyze_return_shape_unrelated_tuple_returns_none():
    wrapper = _func("def pair():\n    return 1, 2\n")
    assert iox._analyze_run_wrapper_return_shape(wrapper) is None


# ---------- _discover_wrapper_return_shapes(): own file + sibling module ----------


def test_discover_wrapper_return_shapes_own_file():
    src = (
        "import subprocess\n"
        "def run_exe(args):\n"
        "    proc = subprocess.run([EXE, *args], capture_output=True)\n"
        "    return proc.returncode, proc.stdout\n"
    )
    tree = ast.parse(src)
    shapes = iox._discover_wrapper_return_shapes(tree, Path("test_fake.py"))
    assert shapes["run_exe"] == {"rc_pos": 0, "stdout_pos": 1}


def test_discover_wrapper_return_shapes_sibling_conftest(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "import subprocess\n"
        "def run_exe(args):\n"
        "    proc = subprocess.run([EXE, *args], capture_output=True)\n"
        "    return proc.returncode, proc.stdout\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "test_thing.py"
    test_file.write_text("def test_it():\n    pass\n", encoding="utf-8")
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    shapes = iox._discover_wrapper_return_shapes(tree, test_file)
    assert shapes["run_exe"] == {"rc_pos": 0, "stdout_pos": 1}


# ---------- _track_result_roles(): tuple-unpack + direct decode-to-local-var ----------


def test_track_result_roles_tuple_unpack():
    func = _func("def test_x():\n    code, out = run_exe(['-h'])\n    assert code == 0\n")
    shapes = {"run_exe": {"rc_pos": 0, "stdout_pos": 1}}
    roles = iox._track_result_roles(func, shapes)
    assert roles == {"code": "rc", "out": "stdout"}


def test_track_result_roles_unknown_wrapper_produces_no_roles():
    func = _func("def test_x():\n    a, b = something_else(['-h'])\n")
    roles = iox._track_result_roles(func, {})
    assert roles == {}


def test_track_result_roles_direct_decode_assignment():
    """The generalization of what _analyze_assertion_helper already did for helper bodies
    -- now works for ANY function, including a test body directly."""
    func = _func(
        "def test_x():\n"
        "    proc = run_exe(['-h'])\n"
        '    err = proc.stderr.decode("utf-8", errors="replace")\n'
        "    assert 'bad' in err\n"
    )
    roles = iox._track_result_roles(func, {})
    assert roles.get("err") == "stderr"


def test_track_result_roles_direct_rc_assignment():
    func = _func(
        "def test_x():\n"
        "    proc = run_exe(['-h'])\n"
        "    code = proc.returncode\n"
        "    assert code == 0\n"
    )
    roles = iox._track_result_roles(func, {})
    assert roles.get("code") == "rc"


# ---------- _track_loop_literal_lists(): for-loop iteration variable -> literal list ----------


def test_track_loop_literal_lists_finds_string_list():
    func = _func(
        "def test_x():\n    for needle in ['a', 'b', 'c']:\n        assert needle in out\n"
    )
    loops = iox._track_loop_literal_lists(func)
    assert loops == {"needle": ["a", "b", "c"]}


def test_track_loop_literal_lists_ignores_non_literal_iterable():
    func = _func(
        "def test_x():\n    for needle in some_dynamic_list():\n        assert needle in out\n"
    )
    loops = iox._track_loop_literal_lists(func)
    assert loops == {}


# ---------- _is_rc_expr / _is_out_expr: attribute OR resolved-role name ----------


def test_is_rc_expr_true_for_direct_attribute():
    node = ast.parse("proc.returncode").body[0].value
    assert iox._is_rc_expr(node, {})


def test_is_rc_expr_true_for_resolved_role_name():
    node = ast.parse("code").body[0].value
    assert iox._is_rc_expr(node, {"code": "rc"})


def test_is_rc_expr_false_for_unresolved_name():
    node = ast.parse("code").body[0].value
    assert not iox._is_rc_expr(node, {})


def test_is_out_expr_true_for_resolved_role_name():
    node = ast.parse("out").body[0].value
    assert iox._is_out_expr(node, {"out": "stdout"})


def test_is_out_expr_false_for_stderr_role():
    """stderr role should NOT satisfy the exact-stdout check -- only stdout does."""
    node = ast.parse("err").body[0].value
    assert not iox._is_out_expr(node, {"err": "stderr"})


# ---------- end-to-end: extract_file() recovers the real solar patterns ----------


def test_extract_file_recovers_tuple_unpacked_rc_check(tmp_path):
    test_file = tmp_path / "test_solar.py"
    test_file.write_text(
        "import subprocess\n"
        "def run_exe(args):\n"
        "    proc = subprocess.run([EXE, *args], capture_output=True)\n"
        "    return proc.returncode, proc.stdout\n"
        "def test_help():\n"
        "    code, out = run_exe(['-h'])\n"
        "    assert code == 0\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    assert cov.skipped == []
    assert cov.examples[0].expect_rc == 0


def test_extract_file_recovers_for_loop_contains_check(tmp_path):
    test_file = tmp_path / "test_solar.py"
    test_file.write_text(
        "import subprocess\n"
        "def run_exe(args):\n"
        "    proc = subprocess.run([EXE, *args], capture_output=True)\n"
        "    return proc.returncode, proc.stdout\n"
        "def test_zhelp():\n"
        "    code, out = run_exe(['-Zhelp'])\n"
        "    assert code == 0\n"
        "    for needle in ['flag-a', 'flag-b', 'flag-c']:\n"
        "        assert needle in out\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    ex = cov.examples[0]
    assert ex.expect_rc == 0
    assert ex.expect_in == ["flag-a", "flag-b", "flag-c"]


def test_extract_file_still_handles_direct_attribute_shape_unchanged(tmp_path):
    """Regression guard: the new role-tracking must not disturb the existing direct
    attribute-access path (result.returncode == 0, snippet in result.stdout)."""
    test_file = tmp_path / "test_plain.py"
    test_file.write_text(
        "def run(args):\n"
        "    import subprocess\n"
        "    return subprocess.run(args, capture_output=True, text=True)\n"
        "def test_help():\n"
        "    r = run(['--help'])\n"
        "    assert r.returncode == 0\n"
        "    assert 'usage' in r.stdout\n",
        encoding="utf-8",
    )
    cov = iox.extract_file(test_file)
    assert cov.n_examples == 1
    ex = cov.examples[0]
    assert ex.expect_rc == 0
    assert ex.expect_in == ["usage"]
