from pathlib import Path

from intake.hardened_runner import RunResult

from scripts.determinex_io_extractor import Example
from scripts.determinex_local_oracle import _run_reimpl


def test_native_reimpl_directory_compiles_and_runs_executable(tmp_path: Path):
    reimpl_dir = tmp_path / "native_tool"
    reimpl_dir.mkdir()
    (reimpl_dir / "reimpl.go").write_text("package main\n", encoding="utf-8")
    (reimpl_dir / "compile.sh").write_text(
        "#!/bin/sh\n"
        "set -e\n"
        "cat > executable <<'EOF'\n"
        "#!/bin/sh\n"
        'printf \'native:%s:%s\\n\' "$1" "$2"\n'
        "EOF\n"
        "chmod +x executable\n",
        encoding="utf-8",
    )

    ex = Example(test="native", argv=["executable", "ok", "again"], expect_rc=0)

    rc, out, err = _run_reimpl(reimpl_dir, ex)

    assert rc == 0, err
    assert out == "native:ok:again\n"
    assert err == ""


def test_native_reimpl_preserves_file_path_argument(tmp_path: Path):
    reimpl_dir = tmp_path / "native_tool"
    reimpl_dir.mkdir()
    (reimpl_dir / "reimpl.go").write_text("package main\n", encoding="utf-8")
    (reimpl_dir / "compile.sh").write_text(
        "#!/bin/sh\n"
        "set -e\n"
        "cat > executable <<'EOF'\n"
        "#!/bin/sh\n"
        'printf \'args:%s:%s\\n\' "$1" "$2"\n'
        "EOF\n"
        "chmod +x executable\n",
        encoding="utf-8",
    )

    ex = Example(test="native_path", argv=["fixtures/input.py", "--json"], expect_rc=0)

    rc, out, err = _run_reimpl(reimpl_dir, ex)

    assert rc == 0, err
    assert out == "args:fixtures/input.py:--json\n"
    assert err == ""


def test_python_reimpl_still_runs_via_python(tmp_path: Path):
    reimpl = tmp_path / "tool.py"
    reimpl.write_text(
        "import sys\nprint('python:' + sys.argv[1])\n",
        encoding="utf-8",
    )

    ex = Example(test="python", argv=["executable", "ok"], expect_rc=0)

    rc, out, err = _run_reimpl(reimpl, ex)

    assert rc == 0
    assert out == "python:ok\n"
    assert err == ""


def test_examples_without_stdin_send_empty_input(monkeypatch, tmp_path: Path):
    reimpl = tmp_path / "tool.py"
    reimpl.write_text("print('unused')\n", encoding="utf-8")
    seen = {}

    def fake_run(cmd, *, workspace, cwd, timeout, extra_env, stdin, output_limit):
        seen["stdin"] = stdin
        return RunResult(
            command=list(cmd),
            cwd=str(cwd),
            exit_code=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("intake.hardened_runner.run", fake_run)

    ex = Example(test="no_stdin", argv=["executable", "--reads-stdin"], expect_rc=0)

    rc, out, err = _run_reimpl(reimpl, ex)

    assert rc == 0
    assert out == ""
    assert err == ""
    assert seen["stdin"] == ""
