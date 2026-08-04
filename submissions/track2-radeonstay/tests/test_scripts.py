from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MATRIX_SCRIPT = PROJECT_ROOT / "scripts" / "run_experiment_matrix.sh"


def test_experiment_matrix_declares_the_controlled_a_to_e_sequence() -> None:
    script = MATRIX_SCRIPT.read_text(encoding="utf-8")

    expected_rows = (
        'A) thinking="on";  flash_attn="off"; batch_size="256"; '
        'ubatch_size="64";  parallel_slots="1"',
        'B) thinking="off"; flash_attn="off"; batch_size="256"; '
        'ubatch_size="64";  parallel_slots="1"',
        'C) thinking="off"; flash_attn="on";  batch_size="256"; '
        'ubatch_size="64";  parallel_slots="1"',
        'D) thinking="off"; flash_attn="on";  batch_size="512"; '
        'ubatch_size="128"; parallel_slots="1"',
        'E) thinking="off"; flash_attn="on";  batch_size="512"; '
        'ubatch_size="128"; parallel_slots="4"',
    )
    for row in expected_rows:
        assert row in script


def test_experiment_matrix_has_safe_dry_run_and_c2_binding() -> None:
    script = MATRIX_SCRIPT.read_text(encoding="utf-8")

    assert "--run A|B|C|D|E|all" in script
    assert "--dry-run" in script
    assert "--expected-commit" in script
    assert "assert_c2_binding" in script
    assert "status --porcelain=v1 --untracked-files=all -- ." in script
    assert "c2_binding_status=verified" in script
    assert script.index("if (( dry_run == 1 ))") < script.index(
        'mkdir -m 0700 -- "${output_root}"'
    )


def test_experiment_matrix_preserves_runs_and_reuses_evidence_collector() -> None:
    script = MATRIX_SCRIPT.read_text(encoding="utf-8")

    assert 'local run_dir="${output_root}/${experiment}"' in script
    assert 'local evidence_dir="${run_dir}/evidence"' in script
    assert "collect_rocm_evidence.sh" in script
    assert "status=failed stage=${current_stage}" in script
    assert "failed_experiments" in script
    assert "compare_benchmarks.py" in script
    assert "A-vs-B-thinking.json" in script
    assert "--require-accepted" in script
    for forbidden_pair in ("A-vs-C", "B-vs-C", "C-vs-D", "D-vs-E"):
        assert forbidden_pair not in script


def test_experiment_matrix_contains_no_destructive_cleanup() -> None:
    script = MATRIX_SCRIPT.read_text(encoding="utf-8").lower()

    forbidden = (
        "rm -rf",
        "rm --",
        "shred ",
        "unlink ",
        "kubectl delete",
        "docker rm",
        "podman rm",
    )
    for command in forbidden:
        assert command not in script


def test_model_launcher_rejects_newline_in_evidence_path(tmp_path: Path) -> None:
    fake_server = tmp_path / "llama\nserver"
    fake_server.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_server.chmod(0o700)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    environment = os.environ.copy()
    environment.update(
        {
            "LLAMA_SERVER": str(fake_server),
            "MODEL_PATH": str(model),
        }
    )

    completed = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "serve_model.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 2
    assert "must not contain CR or LF" in completed.stderr


def test_model_launcher_rechecks_resolved_evidence_paths(tmp_path: Path) -> None:
    physical = tmp_path / "physical\nroot"
    physical.mkdir()
    safe_link = tmp_path / "safe-model-root"
    safe_link.symlink_to(physical, target_is_directory=True)
    fake_server = physical / "llama-server"
    fake_server.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_server.chmod(0o700)
    (physical / "model.gguf").write_bytes(b"model")
    environment = os.environ.copy()
    environment.update(
        {
            "LLAMA_SERVER": str(safe_link / "llama-server"),
            "MODEL_PATH": str(safe_link / "model.gguf"),
        }
    )

    completed = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "serve_model.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 2
    assert "Resolved LLAMA_SERVER" in completed.stderr


def test_evidence_collector_rejects_newline_in_artifact_path(tmp_path: Path) -> None:
    placeholder = str(tmp_path / "placeholder")
    completed = subprocess.run(
        [
            "bash",
            str(PROJECT_ROOT / "scripts" / "collect_rocm_evidence.sh"),
            "--run-id",
            "run-1",
            "--output-dir",
            str(tmp_path / "evidence\nforged"),
            "--retrieval-file",
            placeholder,
            "--quality-file",
            placeholder,
            "--benchmark-file",
            placeholder,
            "--monitor-file",
            placeholder,
            "--server-log",
            placeholder,
            "--model-file",
            placeholder,
            "--llama-server",
            placeholder,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 3
    assert "must not contain CR or LF" in completed.stderr


def test_collectors_recheck_resolved_output_paths(tmp_path: Path) -> None:
    physical = tmp_path / "physical\nroot"
    physical.mkdir()
    safe_link = tmp_path / "safe-output-root"
    safe_link.symlink_to(physical, target_is_directory=True)
    placeholder = str(tmp_path / "placeholder")
    collector = subprocess.run(
        [
            "bash",
            str(PROJECT_ROOT / "scripts" / "collect_rocm_evidence.sh"),
            "--run-id",
            "run-1",
            "--output-dir",
            str(safe_link / "evidence"),
            "--retrieval-file",
            placeholder,
            "--quality-file",
            placeholder,
            "--benchmark-file",
            placeholder,
            "--monitor-file",
            placeholder,
            "--server-log",
            placeholder,
            "--model-file",
            placeholder,
            "--llama-server",
            placeholder,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    monitor = subprocess.run(
        [
            "bash",
            str(PROJECT_ROOT / "scripts" / "monitor_rocm.sh"),
            "--run-id",
            "run-1",
            "--output",
            str(safe_link / "monitor.log"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert collector.returncode == 3
    assert "Resolved output path" in collector.stderr
    assert monitor.returncode == 3
    assert "Resolved monitor paths" in monitor.stderr
