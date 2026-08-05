"""tests/test_rust_executor.py — RustExecutor scaffold + classify smoke.

Doesn't run `cargo build` — that's 90-180s cold and would hammer parallel CI.
The scaffold output is byte-checked: Cargo.toml + src/main.rs + compile.sh +
README, with the right tool/crate name and the clap-4 wiring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from executors import RustExecutor  # noqa: E402

_FAKE_INSTANCE = "burntsushi__ripgrep.3b7fd44"


@pytest.fixture
def synthetic_tasks_dir(tmp_path):
    """Minimal tasks_dir/<instance>/task.yaml fixture for probe()."""
    tdir = tmp_path / "tasks" / _FAKE_INSTANCE
    tdir.mkdir(parents=True)
    (tdir / "task.yaml").write_text(
        "language: rs\nflags: [--help, --version, --json]\n",
        encoding="utf-8",
    )
    (tdir / "tests.json").write_text(
        json.dumps([{"name": f"t_{i}"} for i in range(2538)]),
        encoding="utf-8",
    )
    return tmp_path / "tasks"


def test_scaffold_writes_four_files(synthetic_tasks_dir, tmp_path):
    ex = RustExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, tmp_path / "work")
    src = sc.work_dir / "source"
    assert (src / "Cargo.toml").is_file()
    assert (src / "src" / "main.rs").is_file()
    assert (src / "compile.sh").is_file()
    assert (src / "README_DETERMINEX.md").is_file()
    assert len(sc.files_written) == 4


def test_scaffold_cargo_toml_names_crate_from_tool(synthetic_tasks_dir, tmp_path):
    ex = RustExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, tmp_path / "work")
    cargo = (sc.work_dir / "source" / "Cargo.toml").read_text(encoding="utf-8")
    assert 'name = "ripgrep"' in cargo
    assert "clap" in cargo
    # Release profile is stripped (smaller binary for cleanroom image)
    assert "strip = true" in cargo


def test_scaffold_main_rs_uses_clap_and_iter1_conventions(synthetic_tasks_dir, tmp_path):
    """The Rust scaffold must use clap-4 (so 'error: unexpected argument' is
    emitted natively) and exit rc=1 on usage errors (matching iter-1)."""
    ex = RustExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, tmp_path / "work")
    main_rs = (sc.work_dir / "source" / "src" / "main.rs").read_text(encoding="utf-8")
    assert 'TOOL_NAME: &str = "ripgrep"' in main_rs
    assert "use clap::Parser" in main_rs
    # rc=1 on unknown args / usage errors (NOT clap's default rc=2)
    assert "ExitCode::from(1)" in main_rs
    # POSIX-style file-not-found message (matches Python scaffold)
    assert "No such file or directory" in main_rs


def test_scaffold_compile_sh_uses_cargo_release(synthetic_tasks_dir, tmp_path):
    ex = RustExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, tmp_path / "work")
    compile_sh = (sc.work_dir / "source" / "compile.sh").read_text(encoding="utf-8")
    assert "cargo build --release" in compile_sh
    # Per-instance CARGO_HOME isolation (parallel-worker safety)
    assert "CARGO_HOME" in compile_sh
    assert "CARGO_TARGET_DIR" in compile_sh
    # cp, not symlink — programbench /opt move would break a symlink
    assert "cp " in compile_sh


def test_crate_name_sanitized_for_unusual_tool_names(synthetic_tasks_dir, tmp_path):
    """Tool names with periods or capitals get normalized to a valid Cargo
    package name (lowercase, ascii, _-separated)."""
    # Pretend a tool's instance_id has uppercase + dots
    weird = "author__Tool.Name.Test.abc1234"
    (synthetic_tasks_dir / weird).mkdir()
    (synthetic_tasks_dir / weird / "task.yaml").write_text(
        "language: rs\n",
        encoding="utf-8",
    )
    ex = RustExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(weird)
    sc = ex.scaffold(probe, tmp_path / "work_weird")
    cargo = (sc.work_dir / "source" / "Cargo.toml").read_text(encoding="utf-8")
    # All-lowercase, alnum + _-
    import re

    m = re.search(r'name = "([^"]+)"', cargo)
    assert m, "Cargo.toml missing name"
    name = m.group(1)
    assert name == name.lower(), f"crate name {name!r} not lowercase"
    assert re.match(r"^[a-z0-9_-]+$", name), f"crate name {name!r} not Cargo-safe"


def test_classify_routes_through_central_taxonomy(tmp_path):
    """Inherited classify() goes through determinex_pb_taxonomy. Identical to the
    PythonExecutor test — proves base.Executor's classify is language-neutral."""
    ex = RustExecutor()
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


def test_probe_inherits_python_implementation(synthetic_tasks_dir):
    """RustExecutor.probe delegates to PythonExecutor.probe (task.yaml read
    is language-neutral). Same fixture should give the same ProbeResult."""
    rust_ex = RustExecutor(tasks_dir=synthetic_tasks_dir)
    from executors import PythonExecutor

    py_ex = PythonExecutor(tasks_dir=synthetic_tasks_dir)
    rprobe = rust_ex.probe(_FAKE_INSTANCE)
    pprobe = py_ex.probe(_FAKE_INSTANCE)
    assert rprobe.instance_id == pprobe.instance_id
    assert rprobe.test_count == pprobe.test_count
    assert rprobe.declared_flags == pprobe.declared_flags
