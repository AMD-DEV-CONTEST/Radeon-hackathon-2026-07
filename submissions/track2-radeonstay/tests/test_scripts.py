from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
