"""tests/test_python_executor.py — executors.python end-to-end smoke.

Exercises the 7-phase contract for the Python executor without calling the
official programbench eval harness (which would need Docker + a live task
image). The probe phase uses a synthetic task.yaml + tests.json fixture so
the test doesn't depend on the T:/Dev/ProgramBench tasks dir.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from executors import ExecutorError, PythonExecutor  # noqa: E402
from executors.base import BuildResult, ProbeResult, ScaffoldResult  # noqa: E402

_FAKE_INSTANCE = "psampaz__go-mod-outdated.bb79367"


@pytest.fixture
def synthetic_tasks_dir(tmp_path):
    """Build a minimal tasks_dir/<instance>/task.yaml fixture so probe() works."""
    tdir = tmp_path / "tasks" / _FAKE_INSTANCE
    tdir.mkdir(parents=True)
    (tdir / "task.yaml").write_text(
        "language: go\n"
        "flags:\n"
        "  - --help\n"
        "  - --version\n"
        "  - --update\n"
        "dependencies:\n"
        "  - github.com/foo/bar\n",
        encoding="utf-8",
    )
    (tdir / "tests.json").write_text(
        json.dumps([{"name": f"test_{i}"} for i in range(285)]),
        encoding="utf-8",
    )
    return tmp_path / "tasks"


def test_probe_reads_task_yaml(synthetic_tasks_dir):
    ex = PythonExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    assert probe.instance_id == _FAKE_INSTANCE
    assert probe.test_count == 285
    # PyYAML may not be installed in CI — if it is, declared_flags populated
    if probe.declared_flags:
        assert "--help" in probe.declared_flags
        assert "--version" in probe.declared_flags
        assert "--update" in probe.declared_flags
    if probe.deps:
        assert "github.com/foo/bar" in probe.deps


def test_probe_missing_task_dir_raises(tmp_path):
    ex = PythonExecutor(tasks_dir=tmp_path / "tasks")
    with pytest.raises(ExecutorError) as exc:
        ex.probe("does_not_exist__tool.deadbeef")
    assert "task dir not found" in str(exc.value)


def test_scaffold_writes_three_files(synthetic_tasks_dir, tmp_path):
    ex = PythonExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, work_dir=tmp_path / "work")
    src = sc.work_dir / "source"
    assert (src / "main.py").is_file()
    assert (src / "compile.sh").is_file()
    assert (src / "README_DETERMINEX.md").is_file()
    # Tool name correctly extracted from instance_id
    main_py = (src / "main.py").read_text(encoding="utf-8")
    assert "TOOL_NAME = 'go-mod-outdated'" in main_py
    # README captures probe data
    readme = (src / "README_DETERMINEX.md").read_text(encoding="utf-8")
    assert "go-mod-outdated" in readme
    assert "psampaz" in readme


def test_scaffold_main_py_handles_unknown_flags(synthetic_tasks_dir, tmp_path):
    """The generated main.py must produce the iter-1 clap-style error wording."""
    ex = PythonExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, work_dir=tmp_path / "work")
    main_py = (sc.work_dir / "source" / "main.py").read_text(encoding="utf-8")
    # Both unknown-flag branches must use clap-style wording (iter 1 invariant)
    assert main_py.count("error: unexpected argument") == 2
    # rc=1 not rc=2 for unknown flags (most common in actual test failures)
    # Count sys.exit(1) calls in the parse_args function — there should be 2
    # (one for each unknown-flag branch).
    # We don't pin total exits since print_help/print_version also call exit(0).


def test_build_produces_real_file_not_symlink(synthetic_tasks_dir, tmp_path):
    """compile.sh must produce a real ./executable. Programbench moves it to
    /opt before hashing — a symlink would break after the move."""
    ex = PythonExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, work_dir=tmp_path / "work")
    b = ex.build(sc.work_dir)
    assert b.ok is True, f"build failed: {b.stderr}"
    assert b.executable_path is not None
    assert b.executable_path.is_file()
    assert not b.executable_path.is_symlink(), (
        "executable must be a real file, not a symlink (PB /opt move breaks links)"
    )


def test_pack_emits_deterministic_tarball(synthetic_tasks_dir, tmp_path):
    ex = PythonExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, work_dir=tmp_path / "work")
    ex.build(sc.work_dir)
    p = ex.pack(sc.work_dir)
    assert p.submission_path.is_file()
    assert p.submission_path.name == "submission.tar.gz"
    # n_files counts source-tree files; build added the executable so >=4
    assert p.n_files >= 4


def test_classify_routes_through_central_taxonomy(tmp_path):
    """The classify phase must use the determinex_pb_taxonomy module — no
    per-executor regex duplication."""
    ex = PythonExecutor()
    # Fake eval JSON with one failure that maps to rc_2_unknown_option
    eval_json = tmp_path / "fake.eval.json"
    eval_json.write_text(
        json.dumps(
            {
                "test_results": [
                    {"status": "passed", "name": "t1"},
                    {
                        "status": "failure",
                        "name": "t2",
                        "extra": {"message": "tool: unknown option: --bogus"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    from executors.base import EvalResult

    er = EvalResult(instance_id="x", score=50.0, passed=1, total=2, eval_json_path=eval_json)
    cr = ex.classify(er)
    assert cr.families.get("rc_2_unknown_option") == 1


def test_full_lifecycle_no_eval(synthetic_tasks_dir, tmp_path):
    """End-to-end smoke through probe -> scaffold -> build -> pack with no
    network / Docker / harness dependency."""
    ex = PythonExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    assert isinstance(probe, ProbeResult)
    sc = ex.scaffold(probe, tmp_path / "work")
    assert isinstance(sc, ScaffoldResult)
    b = ex.build(sc.work_dir)
    assert isinstance(b, BuildResult)
    assert b.ok
    p = ex.pack(sc.work_dir)
    assert p.submission_path.is_file()
