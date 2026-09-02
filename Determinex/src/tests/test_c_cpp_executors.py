"""tests/test_c_cpp_executors.py — CExecutor + CppExecutor scaffold smoke.

Single test module for both since they're sister profiles. No `cc`/`c++`
build invocation in tests — that would add toolchain dependency to CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from executors import CExecutor, CppExecutor  # noqa: E402

_FAKE_C_INSTANCE = "lh3__seqtk.94e7070"
_FAKE_CPP_INSTANCE = "facebook__zstd.b2a5f0a"


@pytest.fixture
def synthetic_tasks_dir(tmp_path):
    for iid, lang in [(_FAKE_C_INSTANCE, "c"), (_FAKE_CPP_INSTANCE, "cpp")]:
        tdir = tmp_path / "tasks" / iid
        tdir.mkdir(parents=True)
        (tdir / "task.yaml").write_text(f"language: {lang}\n", encoding="utf-8")
        (tdir / "tests.json").write_text(json.dumps([{"name": "t"}]), encoding="utf-8")
    return tmp_path / "tasks"


# ── C ────────────────────────────────────────────────────────────────────


def test_c_scaffold_writes_three_files(synthetic_tasks_dir, tmp_path):
    ex = CExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_C_INSTANCE)
    sc = ex.scaffold(probe, tmp_path / "work")
    src = sc.work_dir / "source"
    assert (src / "main.c").is_file()
    assert (src / "compile.sh").is_file()
    assert (src / "README_DETERMINEX.md").is_file()


def test_c_main_c_uses_iter1_wording_and_rc1(synthetic_tasks_dir, tmp_path):
    ex = CExecutor(tasks_dir=synthetic_tasks_dir)
    sc = ex.scaffold(ex.probe(_FAKE_C_INSTANCE), tmp_path / "work")
    main_c = (sc.work_dir / "source" / "main.c").read_text(encoding="utf-8")
    assert 'TOOL   = "seqtk"' in main_c
    assert "error: unexpected argument" in main_c
    # rc=1 on unknown args (matching iter-1)
    assert "return 1;" in main_c
    assert "No such file or directory" in main_c


def test_c_compile_sh_uses_cc(synthetic_tasks_dir, tmp_path):
    ex = CExecutor(tasks_dir=synthetic_tasks_dir)
    sc = ex.scaffold(ex.probe(_FAKE_C_INSTANCE), tmp_path / "work")
    compile_sh = (sc.work_dir / "source" / "compile.sh").read_text(encoding="utf-8")
    assert "cc " in compile_sh or "cc\t" in compile_sh
    assert "-O2" in compile_sh
    assert "-std=c11" in compile_sh


# ── C++ ──────────────────────────────────────────────────────────────────


def test_cpp_scaffold_writes_three_files(synthetic_tasks_dir, tmp_path):
    ex = CppExecutor(tasks_dir=synthetic_tasks_dir)
    sc = ex.scaffold(ex.probe(_FAKE_CPP_INSTANCE), tmp_path / "work")
    src = sc.work_dir / "source"
    assert (src / "main.cpp").is_file()
    assert (src / "compile.sh").is_file()
    assert (src / "README_DETERMINEX.md").is_file()


def test_cpp_main_uses_iter1_wording(synthetic_tasks_dir, tmp_path):
    ex = CppExecutor(tasks_dir=synthetic_tasks_dir)
    sc = ex.scaffold(ex.probe(_FAKE_CPP_INSTANCE), tmp_path / "work")
    main_cpp = (sc.work_dir / "source" / "main.cpp").read_text(encoding="utf-8")
    assert 'TOOL_NAME = "zstd"' in main_cpp
    assert "error: unexpected argument" in main_cpp
    # Uses C++17 <filesystem>
    assert "<filesystem>" in main_cpp
    assert "return 1;" in main_cpp


def test_cpp_compile_sh_uses_cpp17(synthetic_tasks_dir, tmp_path):
    ex = CppExecutor(tasks_dir=synthetic_tasks_dir)
    sc = ex.scaffold(ex.probe(_FAKE_CPP_INSTANCE), tmp_path / "work")
    compile_sh = (sc.work_dir / "source" / "compile.sh").read_text(encoding="utf-8")
    assert "c++ " in compile_sh or "c++\t" in compile_sh
    assert "-std=c++17" in compile_sh


# ── Shared invariants across the language family ────────────────────────


@pytest.mark.parametrize(
    "ExClass,iid",
    [
        (CExecutor, _FAKE_C_INSTANCE),
        (CppExecutor, _FAKE_CPP_INSTANCE),
    ],
)
def test_classify_routes_through_central_taxonomy(ExClass, iid, tmp_path):
    """All executors classify through determinex_pb_taxonomy — no per-language drift."""
    ex = ExClass()
    eval_json = tmp_path / "fake.eval.json"
    eval_json.write_text(
        json.dumps(
            {
                "test_results": [
                    {
                        "status": "failure",
                        "name": "t",
                        "extra": {"message": "tool: unknown option: --x"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    from executors.base import EvalResult

    er = EvalResult(instance_id=iid, score=0.0, passed=0, total=1, eval_json_path=eval_json)
    cr = ex.classify(er)
    assert cr.families.get("rc_2_unknown_option") == 1
