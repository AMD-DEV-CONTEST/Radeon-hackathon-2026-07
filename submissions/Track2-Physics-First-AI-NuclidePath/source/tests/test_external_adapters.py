import hashlib
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from nuclear_agent.external_adapters import (
    AdapterPreflightError,
    ExternalSolverManifest,
    GroundwaterSolverAdapter,
    PhreeqcAdapter,
    _terminate_process,
    run_replayable,
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fake(tmp_path, body):
    p = tmp_path / "solver.py"
    p.write_text("#!/usr/bin/env python3\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def manifest(tmp_path, exe, database=None, inputs=()):
    return ExternalSolverManifest(
        executable=exe,
        executable_sha256=digest(exe),
        database=database,
        database_sha256=digest(database) if database else None,
        input_files=tuple((p, digest(p)) for p in inputs),
        version="fake-1",
        command=(str(exe),),
        working_directory=tmp_path,
    )


def test_manifest_is_immutable_and_preflight_runs_hashed_executable(tmp_path):
    exe = fake(tmp_path, "import sys; print('ok'); print('err', file=sys.stderr)")
    m = manifest(tmp_path, exe)
    with pytest.raises(Exception):
        m.version = "changed"
    result = GroundwaterSolverAdapter(m).run()
    assert result.exit_status == 0
    assert result.stdout == "ok\n"
    assert result.stderr == "err\n"
    assert result.stdout_sha256 == hashlib.sha256(b"ok\n").hexdigest()


def test_preflight_rejects_interpreter_indirection(tmp_path):
    exe = fake(tmp_path, "print('ok')")
    indirect = ExternalSolverManifest(
        executable=exe,
        executable_sha256=digest(exe),
        version="fake-1",
        command=(sys.executable, str(exe)),
        working_directory=tmp_path,
    )
    with pytest.raises(AdapterPreflightError, match="directly execute"):
        GroundwaterSolverAdapter(indirect).preflight()


def test_preflight_fails_closed_on_tampering_and_missing_database(tmp_path):
    exe = fake(tmp_path, "print('ok')")
    db = tmp_path / "database.dat"
    db.write_text("original")
    m = manifest(tmp_path, exe, db)
    db.write_text("tampered")
    with pytest.raises(AdapterPreflightError):
        GroundwaterSolverAdapter(m).preflight()
    missing = ExternalSolverManifest(
        executable=exe,
        executable_sha256=digest(exe),
        database=tmp_path / "missing.dat",
        database_sha256="0" * 64,
        version="fake-1",
        command=(str(exe),),
        working_directory=tmp_path,
    )
    with pytest.raises(AdapterPreflightError):
        GroundwaterSolverAdapter(missing).preflight()


def test_input_path_traversal_is_rejected(tmp_path):
    exe = fake(tmp_path, "print('ok')")
    outside = tmp_path.parent / "outside.in"
    outside.write_text("x")
    m = manifest(tmp_path, exe, inputs=(outside,))
    with pytest.raises(AdapterPreflightError):
        GroundwaterSolverAdapter(m).preflight()


def test_timeout_is_captured_as_replayable_failure(tmp_path):
    exe = fake(tmp_path, "import time; print('before', flush=True); time.sleep(2)")
    result = run_replayable(manifest(tmp_path, exe), timeout=0.2)
    assert result.timed_out is True
    assert result.exit_status is None
    assert result.stdout == "before\n"
    assert len(result.stdout_sha256) == 64


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal escalation contract")
def test_timeout_records_sigkill_escalation_when_solver_ignores_sigterm(tmp_path):
    exe = fake(
        tmp_path,
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('before', flush=True); time.sleep(30)",
    )
    result = run_replayable(manifest(tmp_path, exe), timeout=0.2)
    assert result.timed_out and result.exit_status is None
    assert result.timeout_escalated_to_sigkill is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal escalation contract")
def test_sigkill_reap_never_uses_an_unbounded_wait(monkeypatch):
    wait_timeouts = []

    class UnreapableProcess:
        pid = 12345

        def poll(self):
            return None

        def wait(self, timeout=None):
            wait_timeouts.append(timeout)
            if timeout is None:
                raise AssertionError("SIGKILL cleanup must not call wait() without a timeout")
            raise subprocess.TimeoutExpired(["fake-solver"], timeout)

    monkeypatch.setattr(os, "killpg", lambda *_args: None)
    started = time.monotonic()
    assert _terminate_process(
        UnreapableProcess(), deadline=started + 0.05, grace_seconds=0.01,
    ) is True
    assert wait_timeouts and all(timeout is not None for timeout in wait_timeouts)
    assert time.monotonic() - started < 0.5


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-group contract")
def test_timeout_terminates_solver_child_and_grandchild_process_group(tmp_path):
    child = tmp_path / "child.py"
    child.write_text(
        "import os,subprocess,time,pathlib,sys\n"
        "grandchild=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "pathlib.Path('grandchild.pid').write_text(str(grandchild.pid))\n"
        "pathlib.Path('child.pid').write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    exe = fake(
        tmp_path,
        "import os,subprocess,time,pathlib,sys\n"
        "pathlib.Path('leader.pid').write_text(str(os.getpid()))\n"
        f"subprocess.Popen([sys.executable, {str(child)!r}])\n"
        "while not (pathlib.Path('child.pid').exists() and pathlib.Path('grandchild.pid').exists()): time.sleep(.005)\n"
        "print('before', flush=True)\n"
        "time.sleep(30)\n",
    )
    result = run_replayable(manifest(tmp_path, exe), timeout=0.8)
    assert result.timed_out and result.exit_status is None

    def alive(pid):
        status = Path(f"/proc/{pid}/status")
        if not status.exists():
            return False
        return "\nState:\tZ" not in "\n" + status.read_text()

    pids = [int((tmp_path / name).read_text()) for name in
            ("leader.pid", "child.pid", "grandchild.pid")]
    deadline = time.monotonic() + 1
    while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not any(alive(pid) for pid in pids)


def test_non_utf8_solver_output_is_captured_deterministically(tmp_path):
    exe = fake(tmp_path, "import os; os.write(1, b'out\\xff'); os.write(2, b'err\\xfe')")
    result = run_replayable(manifest(tmp_path, exe))
    assert result.exit_status == 0
    assert result.stdout == "out\ufffd"
    assert result.stderr == "err\ufffd"
    assert result.stdout_sha256 == hashlib.sha256(b"out\xff").hexdigest()
    assert result.stderr_sha256 == hashlib.sha256(b"err\xfe").hexdigest()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_stream_limits_fail_closed_and_keep_bounded_raw_evidence(tmp_path, stream):
    descriptor = 1 if stream == "stdout" else 2
    exe = fake(tmp_path, f"import os,time; os.write({descriptor}, b'x'*4096); time.sleep(30)")
    result = run_replayable(manifest(tmp_path, exe), timeout=2, max_stdout_bytes=64,
                            max_stderr_bytes=64)
    assert result.output_limit_exceeded == stream
    assert result.exit_status is None and not result.timed_out
    assert getattr(result, f"{stream}_bytes_observed") > 64
    assert getattr(result, f"{stream}_bytes_retained") == 64
    assert getattr(result, f"{stream}_sha256") == hashlib.sha256(b"x" * 4096).hexdigest()


def test_immediate_dual_stream_overflow_is_deterministic_after_reader_join(tmp_path):
    exe = fake(tmp_path, "import os; os.write(1, b'o'*1025); os.write(2, b'e'*1025)")
    m = manifest(tmp_path, exe)
    for _ in range(100):
        result = run_replayable(m, max_stdout_bytes=1024, max_stderr_bytes=1024)
        assert result.output_limits_exceeded == ("stdout", "stderr")
        assert result.output_limit_exceeded == "stdout"
        assert result.exit_status is None and not result.timed_out


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX escaped-session pipe contract")
@pytest.mark.parametrize("held", ["stdout", "stderr", "both"])
def test_escaped_child_pipe_writers_cannot_block_stream_drain(tmp_path, held):
    stdout = "None" if held in {"stdout", "both"} else "subprocess.DEVNULL"
    stderr = "None" if held in {"stderr", "both"} else "subprocess.DEVNULL"
    exe = fake(
        tmp_path,
        "import pathlib,subprocess,sys\n"
        f"p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], "
        f"start_new_session=True, stdout={stdout}, stderr={stderr})\n"
        "pathlib.Path('escaped.pid').write_text(str(p.pid))\n"
        "print('leader done')\n",
    )
    before = {thread.ident for thread in threading.enumerate()}
    started = time.monotonic()
    try:
        result = run_replayable(manifest(tmp_path, exe), timeout=0.5)
        assert time.monotonic() - started < 1.5
        assert result.exit_status is None
        assert result.stream_drain_timed_out is True
        assert result.streams_complete is False
        assert {thread.ident for thread in threading.enumerate()} == before
    finally:
        pid_file = tmp_path / "escaped.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_stream_limits_require_positive_integers(tmp_path):
    m = manifest(tmp_path, fake(tmp_path, "print('ok')"))
    with pytest.raises(ValueError, match="max_stdout_bytes"):
        run_replayable(m, max_stdout_bytes=0)


def test_phreeqc_has_explicit_configuration(tmp_path):
    assert PhreeqcAdapter.configuration().name == "phreeqc"
    assert PhreeqcAdapter.configuration().scientific_translation is False


def test_preflight_rejects_symlink_artifacts_and_relative_paths(tmp_path):
    exe = fake(tmp_path, "print('ok')")
    link = tmp_path / "solver-link"
    link.symlink_to(exe)
    linked = ExternalSolverManifest(
        executable=link, executable_sha256=digest(exe), version="fake-1",
        command=(str(link),), working_directory=tmp_path,
    )
    with pytest.raises(AdapterPreflightError):
        GroundwaterSolverAdapter(linked).preflight()
    relative = ExternalSolverManifest(
        executable=Path("solver.py"), executable_sha256=digest(exe), version="fake-1",
        command=(str(exe),), working_directory=tmp_path,
    )
    with pytest.raises(AdapterPreflightError, match="absolute"):
        GroundwaterSolverAdapter(relative).preflight()


def test_run_result_records_non_deterministic_duration(tmp_path):
    result = run_replayable(manifest(tmp_path, fake(tmp_path, "print('ok')")))
    assert result.duration_seconds >= 0
