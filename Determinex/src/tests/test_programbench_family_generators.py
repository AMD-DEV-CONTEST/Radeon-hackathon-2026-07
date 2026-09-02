from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN_ROOT = ROOT / "corpus" / "programbench" / "families" / "wave1"


FAMILIES = [
    "rust_cli",
    "search_grep",
    "text_diff",
    "file_renamers",
    "git_wrappers",
    "shell_coreutils",
    "formatters",
]


def _run(
    args: list[str], cwd: Path | None = None, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=20,
    )


def test_all_wave1_generators_emit_compilable_scaffold(tmp_path: Path) -> None:
    probe = tmp_path / "probe.eval.json"
    probe.write_text(
        json.dumps(
            {
                "test_results": [
                    {
                        "name": "tests.test_cli.test_unknown_flag",
                        "status": "failure",
                        "extra": {"message": "error: unexpected argument '--made-up' found"},
                    },
                    {
                        "name": "tests.test_cli.test_invalid_sort",
                        "status": "failure",
                        "extra": {
                            "message": "error: invalid value 'bad' for '--sort <SORT>'\n  [possible values: path, modified, created, accessed]"
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    for family in FAMILIES:
        out = tmp_path / family
        gen = GEN_ROOT / family / "scaffold_generator.py"
        result = _run(
            [
                sys.executable,
                str(gen),
                "--instance",
                f"example__{family}.abc123",
                "--probe-from",
                str(probe),
                "--out",
                str(out),
                "--pack",
            ]
        )
        assert result.returncode == 0, result.stderr
        root = out / f"example__{family}.abc123"
        main_py = root / "source" / "main.py"
        compile_sh = root / "source" / "compile.sh"
        tarball = root / "submission.tar.gz"
        assert main_py.is_file()
        assert compile_sh.is_file()
        assert tarball.is_file()

        pyc = _run([sys.executable, "-m", "py_compile", str(main_py)])
        assert pyc.returncode == 0, pyc.stderr

        help_result = _run([sys.executable, str(main_py), "--help"])
        assert help_result.returncode == 0
        assert "Usage:" in help_result.stdout
        assert family.replace("_", "-") in help_result.stdout

        bad_flag = _run([sys.executable, str(main_py), "--definitely-not-real"])
        assert bad_flag.returncode == 2
        assert "unexpected argument" in bad_flag.stderr


def test_search_grep_generated_scaffold_searches_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    gen = GEN_ROOT / "search_grep" / "scaffold_generator.py"
    _run([sys.executable, str(gen), "--instance", "konradsz__igrep.aa75630", "--out", str(out)])
    main_py = out / "konradsz__igrep.aa75630" / "source" / "main.py"
    data = tmp_path / "data.txt"
    data.write_text("alpha\nneedle here\nomega\n", encoding="utf-8")

    result = _run([sys.executable, str(main_py), "needle", str(data)])
    assert result.returncode == 0
    assert "data.txt:2:needle here" in result.stdout


def test_file_renamer_generated_scaffold_dry_run_table(tmp_path: Path) -> None:
    out = tmp_path / "out"
    gen = GEN_ROOT / "file_renamers" / "scaffold_generator.py"
    _run([sys.executable, str(gen), "--instance", "yaa110__nomino.f892499", "--out", str(out)])
    main_py = out / "yaa110__nomino.f892499" / "source" / "main.py"
    work = tmp_path / "work"
    work.mkdir()
    (work / "file1.txt").write_text("x", encoding="utf-8")

    result = _run(
        [sys.executable, str(main_py), "-t", "-d", str(work), "-r", "file(\\d+)", "renamed_{1}"]
    )
    assert result.returncode == 0
    assert "+-------+--------+" in result.stdout
    assert "renamed_1.txt" in result.stdout
    assert (work / "file1.txt").exists()
