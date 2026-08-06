"""CPU-only contract checks for the distributed multi-robot launcher."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_ROOT / "run_3v3.sh"
WORKER = PROJECT_ROOT / "match_worker.py"
MODEL = PROJECT_ROOT / "models" / "chase_v8_policy.onnx"


FAKE_PYTHON = r'''#!/usr/bin/env python3
import os
import signal
import sys
import time
from pathlib import Path

target = sys.argv[1]
kind = "coordinator" if target.endswith("match_coordinator.py") else "worker"
role = "coordinator"
for index, value in enumerate(sys.argv):
    if value == "--role" and index + 1 < len(sys.argv):
        role = sys.argv[index + 1]
        break

pid_dir = os.environ.get("FAKE_PID_DIR")
if pid_dir:
    Path(pid_dir).mkdir(parents=True, exist_ok=True)
    Path(pid_dir, f"{kind}_{role}_{os.getpid()}.pid").write_text(str(os.getpid()))

behavior = os.environ.get("FAKE_BEHAVIOR", "success")
if behavior == "ignore_term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.pause()
elif behavior == "hang" or behavior == "sigterm":
    signal.pause()
elif behavior == "no_end" and kind == "worker":
    raise SystemExit(1)
elif behavior == "max_steps" and kind == "worker":
    raise SystemExit(3)
elif behavior == "delayed_failure" and kind == "worker" and role == "A_keeper":
    time.sleep(float(os.environ.get("FAKE_FAIL_DELAY", "0.2")))
    raise SystemExit(7)
else:
    if kind == "coordinator":
        delay = float(os.environ.get("FAKE_COORD_DELAY", "0.05"))
    else:
        delay = float(os.environ.get("FAKE_WORKER_DELAY", "0.05"))
    time.sleep(delay)
'''


def make_fake_python(tmp_path: Path) -> Path:
    fake = tmp_path / "fake_python.py"
    fake.write_text(FAKE_PYTHON, encoding="utf-8")
    fake.chmod(0o755)
    return fake


def run_launcher(fake: Path, behavior: str, tmp_path: Path, *args: str,
                 timeout: float = 5,
                 allow_max_steps: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({
        "PYTHON": str(fake),
        "FAKE_BEHAVIOR": behavior,
        "FAKE_PID_DIR": str(tmp_path / "pids"),
        "STARTUP_WAIT": "0.05",
        "TOTAL_TIMEOUT": "2",
        "PORT": "19987",
        "SYNC_HZ": "2",
    })
    if allow_max_steps:
        env["ALLOW_MAX_STEPS_EARLY_EXIT"] = "1"
    return subprocess.run(
        ["bash", str(LAUNCHER), str(MODEL), *args],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def test_launcher_has_valid_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(LAUNCHER)], check=False, timeout=5)
    assert result.returncode == 0


def test_launcher_uses_local_onnx_and_checks_all_workers() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "SCRIPT_DIR=" in source
    assert "/workspace/radeon-repo" not in source
    assert 'PYTHON="${PYTHON:-/opt/venv/bin/python}"' in source
    assert "3 ONNX agents vs 3 rule agents" in source
    assert "*.onnx" in source
    assert '[[ ! -f "$ONNX" ]]' in source
    assert 'WALK_MODEL="$SCRIPT_DIR/models/pretrained/t1_walk.pt"' in source
    assert '[[ ! -f "$WALK_MODEL" ]]' in source

    # Exactly three ONNX workers are started; the remaining three are rules.
    assert source.count('--onnx "$ONNX"') == 3
    assert source.count("start_worker ") >= 6
    assert 'wait "${WORKER_PIDS[$i]}"' in source
    assert "worker_failure_count" in source
    assert "TOTAL_TIMEOUT" in source
    assert 'SYNC_HZ="${SYNC_HZ:-2}"' in source
    assert "--sync-hz \"$SYNC_HZ\"" in source
    assert "trap 'on_signal 130' INT" in source
    assert "END_GRACE" not in source


def test_worker_waits_for_end_or_explicit_step_limit() -> None:
    source = WORKER.read_text(encoding="utf-8")

    assert "N_STEPS = 200" not in source
    assert "--max-steps" in source
    assert "MSG_END" in source
    assert "self.max_steps is None or step < self.max_steps" in source
    assert "return 3 if self.max_steps_reached else 0" in source
    assert "self.received_end = True" in source
    assert "return 1" in source
    assert "rule_walk=False" in source
    assert "models', 'pretrained', 't1_walk.pt" in source


def test_fake_python_success_path(tmp_path: Path) -> None:
    # All six workers and the coordinator exit cleanly.
    fake = make_fake_python(tmp_path)
    result = run_launcher(fake, "success", tmp_path, "1")
    assert result.returncode == 0, result.stdout
    assert "SUCCESS" in result.stdout


def test_fake_python_delayed_worker_failure_is_reported(tmp_path: Path) -> None:
    fake = make_fake_python(tmp_path)
    result = run_launcher(fake, "delayed_failure", tmp_path, "25", timeout=4)
    assert result.returncode == 1, result.stdout
    assert "worker" in result.stdout and "status 7" in result.stdout


def test_fake_python_worker_without_msg_end_is_not_success(tmp_path: Path) -> None:
    fake = make_fake_python(tmp_path)
    result = run_launcher(fake, "no_end", tmp_path, "25", timeout=4)
    assert result.returncode == 1, result.stdout
    assert "worker" in result.stdout and "status 1" in result.stdout


def test_max_steps_requires_explicit_test_mode(tmp_path: Path) -> None:
    fake = make_fake_python(tmp_path)
    incomplete = run_launcher(fake, "max_steps", tmp_path, "25", "1", timeout=4)
    assert incomplete.returncode == 1, incomplete.stdout
    allowed = run_launcher(fake, "max_steps", tmp_path, "25", "1", timeout=4,
                           allow_max_steps=True)
    assert allowed.returncode == 0, allowed.stdout


def test_fake_python_hang_hits_launcher_deadline(tmp_path: Path) -> None:
    fake = make_fake_python(tmp_path)
    result = run_launcher(fake, "hang", tmp_path, "25", timeout=4)
    assert result.returncode == 1, result.stdout
    assert "deadline exceeded" in result.stdout


def test_sigterm_cleans_up_fake_children(tmp_path: Path) -> None:
    fake = make_fake_python(tmp_path)
    env = os.environ.copy()
    env.update({
        "PYTHON": str(fake),
        "FAKE_BEHAVIOR": "sigterm",
        "FAKE_PID_DIR": str(tmp_path / "pids"),
        "STARTUP_WAIT": "0.05",
        "TOTAL_TIMEOUT": "10",
        "PORT": "19988",
    })
    process = subprocess.Popen(
        ["bash", str(LAUNCHER), str(MODEL), "25"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Give all seven wrappers time to write their child pid files.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and len(list((tmp_path / "pids").glob("*.pid"))) < 7:
            time.sleep(0.02)
        assert len(list((tmp_path / "pids").glob("*.pid"))) == 7
        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=4)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)

    assert process.returncode == 143, output
    for pid_path in (tmp_path / "pids").glob("*.pid"):
        pid = int(pid_path.read_text())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            raise AssertionError(f"fake child still exists: {pid}")
        else:
            raise AssertionError(f"fake child still exists: {pid}")


def test_deadline_kills_sigterm_ignoring_children(tmp_path: Path) -> None:
    fake = make_fake_python(tmp_path)
    result = run_launcher(fake, "ignore_term", tmp_path, "25", timeout=4)
    assert result.returncode == 1, result.stdout
    for pid_path in (tmp_path / "pids").glob("*.pid"):
        pid = int(pid_path.read_text())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        else:
            raise AssertionError(f"SIGTERM-ignoring fake child still exists: {pid}")


def test_duration_must_be_positive(tmp_path: Path) -> None:
    fake = make_fake_python(tmp_path)
    result = run_launcher(fake, "success", tmp_path, "0")
    assert result.returncode == 2
    assert "duration must be a positive number" in result.stdout
