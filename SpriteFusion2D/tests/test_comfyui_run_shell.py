# -*- coding: utf-8 -*-
"""Shell-level tests for the R03 start/stop/status ComfyUI run scripts:

    scripts/comfyui_run_lib.sh    (shared helpers, sourced only)
    scripts/start_comfyui.sh
    scripts/stop_comfyui.sh
    scripts/status_comfyui.sh

No real ComfyUI or GPU is required or used. Instead, a small fake
executable stands in for ``$SPRITE_WORKSHOP_COMFY_VENV/bin/python`` -- a
bash script that parses ``--port`` out of its argv (so it keeps the same
"main.py --listen ... --port ... --disable-auto-launch" signature a real
launch would have in ``/proc/<pid>/cmdline``), optionally spawns a real
HTTP server on that port (using the interpreter currently running these
tests, ``sys.executable``) when ``FAKE_COMFY_SERVE=1`` is set, and loops
forever until it receives SIGTERM (unless ``FAKE_COMFY_IGNORE_TERM=1``, to
exercise the SIGKILL escalation path).

Covers the R03 acceptance criteria:

- ``bash -n`` passes for all four files.
- ``--help`` documents the ``SPRITE_WORKSHOP_*`` variables each script
  actually reads.
- Repeated ``start`` does not spawn a second process (idempotent).
- ``stop`` only ever signals the PID the receipt points at, AND only after
  re-verifying that PID's live command line still matches the expected
  ComfyUI invocation -- it must never kill an unrelated process, whether
  that's a completely different process (PID reuse) or a second,
  independently-launched, genuinely-matching ComfyUI-shaped process that
  the receipt never recorded.
- ``status`` checks both PID/command-line liveness AND an HTTP health
  probe, and distinguishes running / unhealthy / stale / stopped.
- All of the above is exercised with paths that contain a space (both the
  ComfyUI root and the run/receipt directory), since the previous version
  of start_comfyui.sh had no space-quoting to worry about at all.

Process liveness is always checked THROUGH bash (``kill -0``), never via
Python's own ``os.kill`` -- on the Windows/MSYS dev machine these tests
were written on, PIDs recorded by a bash script (``$!``) live in the
MSYS/Cygwin PID namespace, which does not line up with native Windows PIDs
that Python's own process APIs would use. Going through bash for every
liveness check keeps this test suite consistent with what the scripts
under test themselves do, and portable to a real Linux box.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIB_SCRIPT = SCRIPTS_DIR / "comfyui_run_lib.sh"
START_SCRIPT = SCRIPTS_DIR / "start_comfyui.sh"
STOP_SCRIPT = SCRIPTS_DIR / "stop_comfyui.sh"
STATUS_SCRIPT = SCRIPTS_DIR / "status_comfyui.sh"

BASH = shutil.which("bash")

FAKE_PYTHON_TEMPLATE = """#!/usr/bin/env bash
# Fake ComfyUI main.py stand-in for R03 shell tests. Keeps the same argv
# signature ("main.py --listen HOST --port PORT --disable-auto-launch") a
# real launch would have, so /proc/<pid>/cmdline-based verification in
# comfyui_run_lib.sh exercises real matching logic, not a mock.
port=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == "--port" ]]; then port="$arg"; fi
  prev="$arg"
done
child=""
if [[ -n "${FAKE_COMFY_SERVE:-}" ]]; then
  "%(python)s" -m http.server "${port:-8000}" --bind 127.0.0.1 >/dev/null 2>&1 &
  child=$!
fi
if [[ -n "${FAKE_COMFY_IGNORE_TERM:-}" ]]; then
  trap '' TERM
else
  trap '[[ -n "$child" ]] && kill "$child" 2>/dev/null; exit 0' TERM
fi
while true; do sleep 1; done
"""


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )


def _bash(script: str, **kwargs) -> subprocess.CompletedProcess:
    return _run([BASH, "-c", script], **kwargs)


def pid_alive(pid: str) -> bool:
    """Liveness check via bash's own kill -0, matching the PID namespace
    the scripts under test operate in (see module docstring)."""
    result = _bash(f'kill -0 {pid} 2>/dev/null')
    return result.returncode == 0


def read_receipt(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not path.is_file():
        return fields
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key] = value
    return fields


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestScriptsExist(unittest.TestCase):
    def test_all_four_files_present_with_shebang(self) -> None:
        for path in (LIB_SCRIPT, START_SCRIPT, STOP_SCRIPT, STATUS_SCRIPT):
            self.assertTrue(path.is_file(), msg=f"missing {path}")
            with path.open("r", encoding="utf-8") as fh:
                first_line = fh.readline()
            self.assertTrue(first_line.startswith("#!"), msg=f"{path} has no shebang")


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestSyntax(unittest.TestCase):
    def test_bash_dash_n_passes_for_all_four_scripts(self) -> None:
        for path in (LIB_SCRIPT, START_SCRIPT, STOP_SCRIPT, STATUS_SCRIPT):
            result = _run([BASH, "-n", str(path)])
            self.assertEqual(
                result.returncode,
                0,
                msg=f"bash -n failed for {path}:\nstdout={result.stdout}\nstderr={result.stderr}",
            )


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestHelp(unittest.TestCase):
    def test_start_help_documents_its_env_vars(self) -> None:
        result = _run([BASH, str(START_SCRIPT), "--help"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for var in (
            "SPRITE_WORKSHOP_COMFY_ROOT",
            "SPRITE_WORKSHOP_COMFY_VENV",
            "SPRITE_WORKSHOP_ROCM_SITE",
            "SPRITE_WORKSHOP_COMFY_PORT",
            "SPRITE_WORKSHOP_COMFY_RUN_DIR",
            "SPRITE_WORKSHOP_COMFY_RECEIPT_FILE",
            "SPRITE_WORKSHOP_COMFY_LOG_FILE",
            "SPRITE_WORKSHOP_COMFY_START_GRACE_SECONDS",
        ):
            self.assertIn(var, result.stdout, msg=f"start --help missing {var}")
        self.assertIn("127.0.0.1", result.stdout)

    def test_stop_help_documents_its_env_vars(self) -> None:
        result = _run([BASH, str(STOP_SCRIPT), "--help"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for var in (
            "SPRITE_WORKSHOP_COMFY_ROOT",
            "SPRITE_WORKSHOP_COMFY_VENV",
            "SPRITE_WORKSHOP_COMFY_RUN_DIR",
            "SPRITE_WORKSHOP_COMFY_RECEIPT_FILE",
            "SPRITE_WORKSHOP_COMFY_STOP_TIMEOUT_SECONDS",
        ):
            self.assertIn(var, result.stdout, msg=f"stop --help missing {var}")

    def test_status_help_documents_its_env_vars(self) -> None:
        result = _run([BASH, str(STATUS_SCRIPT), "--help"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for var in (
            "SPRITE_WORKSHOP_COMFY_ROOT",
            "SPRITE_WORKSHOP_COMFY_VENV",
            "SPRITE_WORKSHOP_COMFY_RUN_DIR",
            "SPRITE_WORKSHOP_COMFY_RECEIPT_FILE",
            "SPRITE_WORKSHOP_COMFY_HEALTH_PATH",
            "SPRITE_WORKSHOP_COMFY_HEALTH_TIMEOUT_SECONDS",
        ):
            self.assertIn(var, result.stdout, msg=f"status --help missing {var}")


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestPureHelpersViaSource(unittest.TestCase):
    """Source comfyui_run_lib.sh (it only defines vars/functions, no main())
    and exercise a few pure helpers directly, without spawning anything."""

    def _source_and_run(self, snippet: str, cwd: Path) -> subprocess.CompletedProcess:
        script = f'source "{LIB_SCRIPT}"\nset +e\n{snippet}\n'
        return _run([BASH, "-c", script], cwd=str(cwd))

    def test_receipt_read_field_missing_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r03-lib-") as tmp:
            result = self._source_and_run(
                'receipt_read_field "no-such-file" "pid"; echo "rc=$?"',
                cwd=Path(tmp),
            )
            self.assertIn("rc=1", result.stdout)

    def test_receipt_read_field_present_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r03-lib-") as tmp:
            tmp_path = Path(tmp)
            receipt = tmp_path / "r.receipt"
            receipt.write_text("pid=4242\nport=8188\n", encoding="utf-8")
            result = self._source_and_run(
                'receipt_read_field "r.receipt" "pid"',
                cwd=tmp_path,
            )
            self.assertEqual(result.stdout.strip(), "4242")

    def test_pid_is_running_true_for_self_shell(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r03-lib-") as tmp:
            result = self._source_and_run(
                'pid_is_running "$$"; echo "rc=$?"',
                cwd=Path(tmp),
            )
            self.assertIn("rc=0", result.stdout)

    def test_pid_is_running_false_for_implausible_pid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r03-lib-") as tmp:
            result = self._source_and_run(
                'pid_is_running "999999999"; echo "rc=$?"',
                cwd=Path(tmp),
            )
            self.assertIn("rc=1", result.stdout)

    def test_process_matches_target_false_for_non_comfyui_shell(self) -> None:
        # The test runner's own bash shell is alive but its cmdline does not
        # contain "main.py"/"--port <n>", so it must never be treated as a
        # match, whatever port is asked about.
        with tempfile.TemporaryDirectory(prefix="r03-lib-") as tmp:
            result = self._source_and_run(
                'SPRITE_WORKSHOP_COMFY_VENV="/nonexistent-venv"; process_matches_target "$$" "8188"; echo "rc=$?"',
                cwd=Path(tmp),
            )
            self.assertIn("rc=1", result.stdout)


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestRunLifecycle(unittest.TestCase):
    """Functional tests that actually start/stop/status a fake ComfyUI
    process tree, entirely under a temp directory whose names deliberately
    contain a space (both the ComfyUI root and the run dir) to exercise the
    scripts' path quoting."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="r03-run-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)

        # Deliberately spaced directory names.
        self.comfy_root = root / "My ComfyUI Root"
        self.comfy_venv = root / "comfyui venv"
        self.run_dir = root / "comfyui run dir"

        self.comfy_root.mkdir(parents=True)
        (self.comfy_root / "main.py").write_text("# fake main.py\n", encoding="utf-8")
        (self.comfy_venv / "bin").mkdir(parents=True)

        python_bin = self.comfy_venv / "bin" / "python"
        python_bin.write_text(
            FAKE_PYTHON_TEMPLATE % {"python": sys.executable.replace("\\", "/")},
            encoding="utf-8",
            newline="\n",
        )
        python_bin.chmod(0o755)
        self.python_bin = python_bin

        self.receipt_file = self.run_dir / "comfyui.receipt"
        self.log_file = self.run_dir / "comfyui.log"

        self.base_env = {
            "PATH": __import__("os").environ.get("PATH", ""),
            "SPRITE_WORKSHOP_COMFY_ROOT": str(self.comfy_root),
            "SPRITE_WORKSHOP_COMFY_VENV": str(self.comfy_venv),
            "SPRITE_WORKSHOP_ROCM_SITE": str(root / "rocm-site"),
            "SPRITE_WORKSHOP_COMFY_RUN_DIR": str(self.run_dir),
            "SPRITE_WORKSHOP_COMFY_RECEIPT_FILE": str(self.receipt_file),
            "SPRITE_WORKSHOP_COMFY_LOG_FILE": str(self.log_file),
            "SPRITE_WORKSHOP_COMFY_HEALTH_PATH": "/",
            "SPRITE_WORKSHOP_COMFY_START_GRACE_SECONDS": "1",
            "SPRITE_WORKSHOP_COMFY_STOP_TIMEOUT_SECONDS": "3",
            "SPRITE_WORKSHOP_COMFY_HEALTH_TIMEOUT_SECONDS": "3",
        }

        self._spawned_pids: list[str] = []

    def tearDown(self) -> None:
        # Best-effort cleanup of anything a test left running.
        for pid in self._spawned_pids:
            _bash(f"kill -9 {pid} 2>/dev/null")

    def _env(self, port: str, **overrides) -> dict[str, str]:
        env = dict(self.base_env)
        env["SPRITE_WORKSHOP_COMFY_PORT"] = port
        env.update(overrides)
        return env

    def _start(self, port: str, **overrides) -> subprocess.CompletedProcess:
        return _run([BASH, str(START_SCRIPT)], env=self._env(port, **overrides))

    def _stop(self, port: str, **overrides) -> subprocess.CompletedProcess:
        return _run([BASH, str(STOP_SCRIPT)], env=self._env(port, **overrides))

    def _status(self, port: str, **overrides) -> subprocess.CompletedProcess:
        return _run([BASH, str(STATUS_SCRIPT)], env=self._env(port, **overrides))

    def _spawn_extra_matching_process(self, port: str, **env_overrides) -> str:
        """Directly launches a second fake-ComfyUI process with the exact
        same argv signature start_comfyui.sh would use, WITHOUT going
        through start_comfyui.sh (so no receipt ever points at it). Returns
        its PID as a string, obtained via bash's own $! so it is in the
        same PID namespace kill -0/ps use."""
        env_prefix = "".join(f'{k}="{v}" ' for k, v in env_overrides.items())
        cmd = (
            f'cd "{self.comfy_root}" && '
            f'({env_prefix}"{self.python_bin}" main.py --listen 127.0.0.1 '
            f'--port {port} --disable-auto-launch >/dev/null 2>&1 & echo $!)'
        )
        result = _bash(cmd)
        pid = result.stdout.strip()
        self.assertTrue(pid.isdigit(), msg=f"failed to spawn extra process: {result.stdout!r} {result.stderr!r}")
        self._spawned_pids.append(pid)
        time.sleep(0.5)
        return pid

    # -- repeated start must not double-start -----------------------------

    def test_repeated_start_does_not_produce_a_second_process(self) -> None:
        r1 = self._start("18801")
        self.assertEqual(r1.returncode, 0, msg=f"stdout={r1.stdout}\nstderr={r1.stderr}")
        fields1 = read_receipt(self.receipt_file)
        pid1 = fields1.get("pid")
        self.assertTrue(pid1 and pid1.isdigit(), msg=fields1)
        self.assertTrue(pid_alive(pid1))
        self._spawned_pids.append(pid1)

        r2 = self._start("18801")
        self.assertEqual(r2.returncode, 0, msg=f"stdout={r2.stdout}\nstderr={r2.stderr}")
        self.assertIn("already running", r2.stderr)
        fields2 = read_receipt(self.receipt_file)
        pid2 = fields2.get("pid")
        self.assertEqual(pid1, pid2, msg="second start must not replace/duplicate the running pid")

        # A third call for good measure.
        r3 = self._start("18801")
        self.assertEqual(r3.returncode, 0)
        fields3 = read_receipt(self.receipt_file)
        self.assertEqual(pid1, fields3.get("pid"))

        stop_result = self._stop("18801")
        self.assertEqual(stop_result.returncode, 0, msg=stop_result.stderr)
        self.assertFalse(pid_alive(pid1))
        self.assertFalse(self.receipt_file.exists())

    # -- stop only touches the receipt-designated, cmdline-matching pid ---

    def test_stop_leaves_unrelated_process_untouched_pid_reuse_case(self) -> None:
        # Spawn a plain, non-ComfyUI-shaped background process and point a
        # hand-crafted receipt at it, simulating PID reuse after the real
        # ComfyUI process already exited.
        result = _bash('(while true; do sleep 1; done) & echo $!')
        unrelated_pid = result.stdout.strip()
        self.assertTrue(unrelated_pid.isdigit(), msg=result.stdout)
        self._spawned_pids.append(unrelated_pid)
        time.sleep(0.3)
        self.assertTrue(pid_alive(unrelated_pid))

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.receipt_file.write_text(
            textwrap.dedent(
                f"""\
                receipt_version=1
                pid={unrelated_pid}
                port=18802
                listen_host=127.0.0.1
                comfy_root={self.comfy_root}
                comfy_venv={self.comfy_venv}
                python_bin={self.python_bin}
                log_file={self.log_file}
                health_path=/
                started_at=2026-01-01T00:00:00Z
                """
            ),
            encoding="utf-8",
        )

        status_result = self._status("18802")
        self.assertEqual(status_result.returncode, 3, msg=status_result.stdout + status_result.stderr)
        self.assertIn("status=stale", status_result.stdout)

        stop_result = self._stop("18802")
        self.assertEqual(
            stop_result.returncode, 1, msg=f"stdout={stop_result.stdout}\nstderr={stop_result.stderr}"
        )
        self.assertIn("does NOT match", stop_result.stderr)
        self.assertTrue(pid_alive(unrelated_pid), msg="stop must never kill a non-matching pid")
        self.assertTrue(self.receipt_file.exists(), msg="stop must leave a refused receipt in place")

    def test_stop_does_not_touch_a_second_genuinely_matching_but_unrecorded_instance(self) -> None:
        # Start the managed instance on port A via start_comfyui.sh.
        r1 = self._start("18803")
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)
        managed_pid = read_receipt(self.receipt_file).get("pid")
        self.assertTrue(managed_pid and pid_alive(managed_pid))
        self._spawned_pids.append(managed_pid)

        # Independently launch a second, equally ComfyUI-shaped process on a
        # different port, bypassing start_comfyui.sh entirely -- the
        # receipt never learns about this one.
        extra_pid = self._spawn_extra_matching_process("18804")
        self.assertTrue(pid_alive(extra_pid))

        stop_result = self._stop("18803")
        self.assertEqual(stop_result.returncode, 0, msg=stop_result.stderr)

        self.assertFalse(pid_alive(managed_pid), msg="the managed pid must be stopped")
        self.assertTrue(pid_alive(extra_pid), msg="an unrecorded process must never be touched by stop")

        _bash(f"kill -9 {extra_pid} 2>/dev/null")

    def test_stop_escalates_to_sigkill_when_process_ignores_sigterm(self) -> None:
        r1 = self._start("18805", FAKE_COMFY_IGNORE_TERM="1")
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)
        pid = read_receipt(self.receipt_file).get("pid")
        self.assertTrue(pid and pid_alive(pid))
        self._spawned_pids.append(pid)

        started = time.time()
        stop_result = self._stop("18805")
        elapsed = time.time() - started
        self.assertEqual(stop_result.returncode, 0, msg=stop_result.stderr)
        self.assertIn("escalating to SIGKILL", stop_result.stderr)
        self.assertFalse(pid_alive(pid))
        # Must have actually waited out the (3s, per base_env) SIGTERM
        # grace period before escalating, not killed instantly.
        self.assertGreaterEqual(elapsed, 2.5)

    def test_stop_and_status_recognize_a_stale_receipt_with_dead_pid(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.receipt_file.write_text(
            textwrap.dedent(
                f"""\
                receipt_version=1
                pid=999999999
                port=18806
                listen_host=127.0.0.1
                comfy_root={self.comfy_root}
                comfy_venv={self.comfy_venv}
                python_bin={self.python_bin}
                log_file={self.log_file}
                health_path=/
                started_at=2026-01-01T00:00:00Z
                """
            ),
            encoding="utf-8",
        )

        status_result = self._status("18806")
        self.assertEqual(status_result.returncode, 3)
        self.assertIn("status=stale", status_result.stdout)
        self.assertTrue(self.receipt_file.exists(), msg="status must not mutate/delete the receipt")

        stop_result = self._stop("18806")
        self.assertEqual(stop_result.returncode, 0, msg=stop_result.stderr)
        self.assertIn("removing stale receipt", stop_result.stderr)
        self.assertFalse(self.receipt_file.exists())

    def test_status_with_no_receipt_reports_stopped(self) -> None:
        result = self._status("18807")
        self.assertEqual(result.returncode, 1)
        self.assertIn("status=stopped", result.stdout)

    # -- status checks BOTH pid/cmdline AND an HTTP probe ------------------

    def test_status_reports_running_when_pid_matches_and_http_responds(self) -> None:
        r1 = self._start("18808", FAKE_COMFY_SERVE="1")
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)
        pid = read_receipt(self.receipt_file).get("pid")
        self._spawned_pids.append(pid)

        status_result = self._status("18808")
        self.assertEqual(status_result.returncode, 0, msg=status_result.stdout + status_result.stderr)
        self.assertIn("status=running", status_result.stdout)
        self.assertIn(f"pid={pid}", status_result.stdout)

        self._stop("18808")

    def test_status_reports_unhealthy_when_pid_matches_but_http_does_not_respond(self) -> None:
        # No FAKE_COMFY_SERVE -- the process is alive and cmdline-matching,
        # but nothing is actually listening on the port.
        r1 = self._start("18809")
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)
        pid = read_receipt(self.receipt_file).get("pid")
        self._spawned_pids.append(pid)

        status_result = self._status("18809")
        self.assertEqual(status_result.returncode, 2, msg=status_result.stdout + status_result.stderr)
        self.assertIn("status=unhealthy", status_result.stdout)

        self._stop("18809")

    # -- paths containing a space are quoted correctly end to end ---------

    def test_full_lifecycle_with_spaces_in_every_configurable_path(self) -> None:
        # setUp already put spaces in comfy_root, comfy_venv and run_dir;
        # this test additionally spaces out the log file name explicitly
        # and runs start -> status -> stop end to end, asserting each step
        # succeeds and the receipt records the exact spaced paths verbatim.
        spaced_log = self.run_dir / "comfy ui log file.log"
        env = self._env("18810", FAKE_COMFY_SERVE="1", SPRITE_WORKSHOP_COMFY_LOG_FILE=str(spaced_log))

        start_result = _run([BASH, str(START_SCRIPT)], env=env)
        self.assertEqual(start_result.returncode, 0, msg=f"stdout={start_result.stdout}\nstderr={start_result.stderr}")

        fields = read_receipt(self.receipt_file)
        self.assertEqual(fields.get("comfy_root"), str(self.comfy_root))
        self.assertEqual(fields.get("comfy_venv"), str(self.comfy_venv))
        self.assertEqual(fields.get("log_file"), str(spaced_log))
        self.assertTrue(spaced_log.exists(), msg="ComfyUI stdout/stderr log must be created at the spaced path")

        pid = fields.get("pid")
        self._spawned_pids.append(pid)

        status_result = _run([BASH, str(STATUS_SCRIPT)], env=env)
        self.assertEqual(status_result.returncode, 0, msg=status_result.stdout + status_result.stderr)
        self.assertIn("status=running", status_result.stdout)

        stop_result = _run([BASH, str(STOP_SCRIPT)], env=env)
        self.assertEqual(stop_result.returncode, 0, msg=stop_result.stderr)
        self.assertFalse(pid_alive(pid))
        self.assertFalse(self.receipt_file.exists())


if __name__ == "__main__":
    unittest.main()
