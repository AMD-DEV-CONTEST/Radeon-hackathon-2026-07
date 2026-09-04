from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest


def test_demo_script_has_valid_shell_syntax():
    result = subprocess.run(
        ["bash", "-n", "scripts/run_demo.sh"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_run_demo_starts_mock_ui(tmp_path):
    port = _free_port()
    repo = Path.cwd()
    qdrant_path = tmp_path / "qdrant"
    shutil.copytree(repo / "data/qdrant/legal", qdrant_path)
    environment = {
        **os.environ,
        "ACCIDENT_RIGHTS_PYTHON": str(repo / ".venv/bin/python"),
        "DEMO_MODE": "mock",
        "MODEL_MODE": "mock",
        "GRADIO_SERVER_NAME": "127.0.0.1",
        "GRADIO_SERVER_PORT": str(port),
        "CASE_ROOT": str(tmp_path / "cases"),
        "ORCHESTRATOR_CHECKPOINT_DB": str(tmp_path / "checkpoints.sqlite3"),
        "QDRANT_PATH": str(qdrant_path),
        "LEGAL_CORPUS_DB": str(
            (repo / "data/laws/legal_corpus.sqlite3").resolve()
        ),
        "REPORT_ROOT": str(tmp_path / "reports"),
        "DEMO_RUNTIME_DIR": str(tmp_path / "runtime"),
    }
    process = subprocess.Popen(
        ["bash", "scripts/run_demo.sh"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = ""
    try:
        # Importing Gradio twice (doctor + server) is slow on a cold macOS
        # Python 3.14 process. The product's mock-mode acceptance target is 90s.
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output += process.stdout.read() if process.stdout else ""
                raise AssertionError(f"run_demo.sh exited early:\n{output}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}", timeout=1
                ) as response:
                    assert response.status == 200
                    break
            except Exception:
                time.sleep(0.25)
        else:
            raise AssertionError(
                "UI did not start in 90 seconds; inspect the test runtime log."
            )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip(
                "The current sandbox forbids loopback binds; run this test "
                "outside the filesystem-only sandbox."
            )
        return int(listener.getsockname()[1])
