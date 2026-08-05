"""tests/test_go_executor.py — GoExecutor scaffold + classify smoke."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from executors import GoExecutor  # noqa: E402

_FAKE_INSTANCE = "psampaz__go-mod-outdated.bb79367"


@pytest.fixture
def synthetic_tasks_dir(tmp_path):
    tdir = tmp_path / "tasks" / _FAKE_INSTANCE
    tdir.mkdir(parents=True)
    (tdir / "task.yaml").write_text(
        "language: go\nflags: [--help, --version, --update]\n",
        encoding="utf-8",
    )
    (tdir / "tests.json").write_text(
        json.dumps([{"name": f"t_{i}"} for i in range(285)]),
        encoding="utf-8",
    )
    return tmp_path / "tasks"


def test_scaffold_writes_four_files(synthetic_tasks_dir, tmp_path):
    ex = GoExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, tmp_path / "work")
    src = sc.work_dir / "source"
    assert (src / "go.mod").is_file()
    assert (src / "main.go").is_file()
    assert (src / "compile.sh").is_file()
    assert (src / "README_DETERMINEX.md").is_file()
    assert len(sc.files_written) == 4


def test_go_mod_module_name_normalized(synthetic_tasks_dir, tmp_path):
    ex = GoExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, tmp_path / "work")
    gomod = (sc.work_dir / "source" / "go.mod").read_text(encoding="utf-8")
    # Tool name "go-mod-outdated" → module name "go-mod-outdated" (hyphens allowed)
    assert "module go-mod-outdated" in gomod
    # Go version pinned
    assert "go 1.21" in gomod


def test_main_go_uses_iter1_clap_wording_and_rc1(synthetic_tasks_dir, tmp_path):
    """Go scaffold must emit the same clap-style 'error: unexpected argument'
    + rc=1 wording as the Python and Rust scaffolds so cross-language goldens
    stay aligned."""
    ex = GoExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, tmp_path / "work")
    main_go = (sc.work_dir / "source" / "main.go").read_text(encoding="utf-8")
    assert 'toolName    = "go-mod-outdated"' in main_go
    assert "error: unexpected argument" in main_go
    # rc=1 for unknown flags (matching iter-1 / matching Rust scaffold)
    assert "os.Exit(1)" in main_go
    # POSIX-style file-not-found message
    assert "No such file or directory" in main_go


def test_compile_sh_stdlib_only(synthetic_tasks_dir, tmp_path):
    """Compile script must NOT pull external deps (stdlib only → cold build <3s)."""
    ex = GoExecutor(tasks_dir=synthetic_tasks_dir)
    probe = ex.probe(_FAKE_INSTANCE)
    sc = ex.scaffold(probe, tmp_path / "work")
    compile_sh = (sc.work_dir / "source" / "compile.sh").read_text(encoding="utf-8")
    assert "go build" in compile_sh
    # No actual `go mod download` / `go get` invocation — stdlib only.
    # Check that those commands aren't INVOKED (not just mentioned in comments).
    code_lines = [
        ln for ln in compile_sh.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    code_blob = "\n".join(code_lines)
    assert "go mod download" not in code_blob, (
        f"stdlib-only build must not call `go mod download`; found in: {code_blob}"
    )
    assert "go get " not in code_blob, (
        f"stdlib-only build must not call `go get`; found in: {code_blob}"
    )
    # Per-instance GOPATH / GOCACHE isolation
    assert "GOPATH" in compile_sh
    assert "GOCACHE" in compile_sh


def test_classify_routes_through_central_taxonomy(tmp_path):
    ex = GoExecutor()
    eval_json = tmp_path / "fake.eval.json"
    eval_json.write_text(
        json.dumps(
            {
                "test_results": [
                    {
                        "status": "failure",
                        "name": "t",
                        "extra": {"message": "tool: unknown option: --bogus"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    from executors.base import EvalResult

    er = EvalResult(instance_id="x", score=0.0, passed=0, total=1, eval_json_path=eval_json)
    cr = ex.classify(er)
    assert cr.families.get("rc_2_unknown_option") == 1
