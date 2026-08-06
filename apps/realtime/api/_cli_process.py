"""Generic long-running CLI-subprocess wrapper used by teleop / record / (later) train.

Factored out of ``teleop_control._TeleopCLIProcess`` on 2026-04-21 so we
don't copy-paste the same 200 lines of subprocess plumbing into every
feature. Same 2-stage readiness gate, same SIGTERM-then-SIGKILL teardown,
same ANSI-stripping log-tail reader thread, same "feed a few newlines into
stdin to auto-accept calibration prompts" trick.

Design choices worth flagging for future maintainers:
  * We deliberately use ``subprocess.Popen`` + a daemon reader thread rather
    than ``asyncio.create_subprocess_exec`` (what MakerMods does). Both work,
    but the threading flavour integrates more cleanly with our existing
    FastAPI routes that call ``asyncio.to_thread(proc.start)``.
  * ``start_new_session=True`` puts the child in its own process group so we
    can ``os.killpg`` the whole tree on stop — important because
    ``lerobot-record`` spawns a ffmpeg encoder child per camera.
  * ``stderr`` is merged into ``stdout`` so one reader drains both. Anything
    that looked like a traceback / error gets remembered in ``last_error``
    to surface through the API.
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional

logger = logging.getLogger(__name__)

# Shared with teleop_control so the two agree on how many log lines we keep
# for the UI status panel.
DEFAULT_LOG_TAIL_LINES = 120

# Strips ANSI cursor/colour escapes (lerobot CLIs print a live FPS banner
# using ``\x1b[2J\x1b[H`` which otherwise leaks into the API response).
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# Map console_scripts → python -m module (fallback when venv shebang is broken).
_CLI_MODULE_FALLBACK: dict[str, str] = {
    "lerobot-teleoperate": "lerobot.scripts.lerobot_teleoperate",
    "lerobot-record": "lerobot.scripts.lerobot_record",
    "lerobot-calibrate": "lerobot.scripts.lerobot_calibrate",
    "lerobot-dataset-viz": "lerobot.scripts.lerobot_dataset_viz",
    "motorbridge-cli": "motorbridge.cli",
    "motorbridge-gateway": "motorbridge.gateway",
}


def _venv_bin_dirs() -> List[Path]:
    """Candidate venv bin/ dirs, most specific first."""
    seen: set[str] = set()
    dirs: List[Path] = []

    def add(p: Path) -> None:
        key = str(p)
        if key not in seen:
            seen.add(key)
            dirs.append(p)

    add(Path(sys.executable).resolve().parent)
    for key in ("BOTVERSEX_LEROBOT_VENV", "REBOT_LEROBOT_VENV"):
        raw = os.environ.get(key)
        if raw:
            add(Path(raw).expanduser().resolve() / "bin")
    bx = os.environ.get("BOTVERSEX_HOME")
    if bx:
        add(Path(bx).expanduser().resolve() / "venv" / "bin")
    add(Path.home() / "venvs" / "lerobot" / "bin")
    add(Path.home() / ".botversex" / "venv" / "bin")
    return dirs


def _script_interpreter_exists(script: Path) -> bool:
    """True if a #! script's interpreter path exists (ELF binaries always ok)."""
    try:
        first = script.read_bytes().split(b"\n", 1)[0]
        if not first.startswith(b"#!"):
            return True
        interp = first[2:].decode("utf-8", errors="replace").strip().split()[0]
        return bool(interp) and os.path.isfile(interp)
    except OSError:
        return False


def _python_in_bin(bin_dir: Path) -> Optional[Path]:
    for name in ("python3.12", "python3", "python"):
        py = bin_dir / name
        if py.is_file() and os.access(py, os.X_OK):
            return py
    return None


def resolve_cli_argv(name: str) -> List[str]:
    """Return argv prefix to launch a CLI, tolerating broken venv shebangs."""
    for bin_dir in _venv_bin_dirs():
        script = bin_dir / name
        if script.is_file() and os.access(script, os.X_OK) and _script_interpreter_exists(script):
            return [str(script)]

    module = _CLI_MODULE_FALLBACK.get(name)
    if module:
        for bin_dir in _venv_bin_dirs():
            py = _python_in_bin(bin_dir)
            if py is None:
                continue
            try:
                subprocess.run(
                    [str(py), "-c", f"import {module.split('.')[0]}"],
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                return [str(py), "-m", module]
            except (subprocess.SubprocessError, OSError):
                continue

    which = shutil.which(name)
    if which:
        return [which]
    return [name]


def resolve_cli_binary(name: str) -> str:
    """Return an absolute path to ``<venv>/bin/<name>`` if it exists.

    Prefer ``resolve_cli_argv()`` when spawning subprocesses — this helper
    remains for simple call sites but may return a broken shebang script.
    """
    argv = resolve_cli_argv(name)
    return argv[0]


class CLIProcess:
    """Owns one long-running CLI subprocess + a log-tail reader thread.

    Subclasses supply the command and (optionally) extra env vars /
    readiness regex patterns. Lifecycle is identical across features:

        proc = SomeCLIProcess(...)
        proc.start()            # blocks until we think it's ready
        ...
        proc.stop()             # SIGTERM, then SIGKILL after ``stop_timeout_s``
    """

    # Subclasses can override: a tuple of regex patterns that, once any of
    # them matches the recent log tail, is taken as "the CLI is happy".
    ready_patterns: tuple[re.Pattern, ...] = ()

    # Human-readable tag used in log lines and in ``to_status()``.
    role: str = "cli"

    def __init__(
        self,
        *,
        log_tail_lines: int = DEFAULT_LOG_TAIL_LINES,
        session_id: Optional[str] = None,
    ) -> None:
        self.session_id = session_id or f"{self.role}-{uuid.uuid4().hex[:8]}"
        self.started_at = time.time()

        self._proc: Optional[subprocess.Popen] = None
        self._log: Deque[str] = deque(maxlen=log_tail_lines)
        self._reader: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Hooks subclasses are expected to implement.
    # ------------------------------------------------------------------
    def build_cmd(self) -> List[str]:  # pragma: no cover - abstract
        raise NotImplementedError

    def build_env(self) -> dict:
        """Return the env dict the subprocess is launched with.

        Default: inherit parent env, force Python unbuffered output.
        Subclasses can extend but should generally call ``super().build_env()``.
        """
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        # lerobot CLIs will try to bring up a rerun TCP viewer unless told
        # otherwise. We don't use it; disable to avoid fighting any other
        # rerun instance (e.g. MakerMods) that might be running.
        env.setdefault("RERUN", "off")
        return env

    # ------------------------------------------------------------------
    # Logging helpers.
    # ------------------------------------------------------------------
    def _log_line(self, s: str) -> None:
        s = _ANSI_ESCAPE_RE.sub("", s).rstrip()
        if not s:
            return
        stamp = time.strftime("%H:%M:%S")
        self._log.append(f"{stamp} {s}")
        # Also forward to stdout so `tail -f /tmp/botversex_realtime.log`
        # shows live output even when uvicorn --reload eats logger.info().
        print(f"[{self.role}] {stamp} {s}", flush=True)

    @property
    def log_tail(self) -> List[str]:
        return list(self._log)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # ------------------------------------------------------------------
    # Lifecycle.
    # ------------------------------------------------------------------
    def start(
        self,
        ready_timeout_s: float = 8.0,
        *,
        keep_stdin_open: bool = False,
        auto_accept_prompts: bool = True,
    ) -> None:
        """Spawn the CLI. Raises ``RuntimeError`` if it dies during startup."""
        cmd = self.build_cmd()
        self._log_line("spawn: " + " ".join(shlex.quote(x) for x in cmd))

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                env=self.build_env(),
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"{cmd[0]} not found ({exc}). Is the realtime venv set up?"
            ) from exc

        # Feed a few newlines so any residual interactive prompt auto-accepts.
        # Interactive flows (e.g. lerobot-calibrate) keep stdin open for Web UI.
        if auto_accept_prompts and not keep_stdin_open:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.write("\n\n\n")
                    self._proc.stdin.flush()
                    self._proc.stdin.close()
            except Exception as exc:  # non-fatal
                self._log_line(f"[WARN] failed to feed stdin newlines: {exc}")

        self._reader = threading.Thread(
            target=self._drain_output,
            daemon=True,
            name=f"{self.role}-reader-{self.session_id}",
        )
        self._reader.start()

        # 2-stage readiness gate:
        #   1. Poll for ``ready_timeout_s``. If any ``ready_patterns`` regex
        #      hits the tail → green light. If proc exits → raise.
        #   2. If no marker appeared but proc is still alive, assume ready.
        t0 = time.time()
        while time.time() - t0 < ready_timeout_s:
            rc = self._proc.poll()
            if rc is not None:
                tail = "\n    ".join(self._log) or "(no output)"
                raise RuntimeError(
                    f"{self.role} exited with code {rc} before it was ready. "
                    f"Recent output:\n    {tail}"
                )
            if self.ready_patterns:
                recent = "\n".join(list(self._log)[-20:])
                if any(p.search(recent) for p in self.ready_patterns):
                    self._log_line("CLI looks ready")
                    return
            time.sleep(0.1)

        if self._proc.poll() is None:
            # B601 teleop configure can take 30-90s. We extend the timeout
            # rather than falsely assuming ready, because if configure hasn't
            # printed "Teleop loop time:" yet the arm is NOT following the
            # leader — telling the user "running" would be a lie.
            extra = 90.0
            deadline = time.time() + extra
            while time.time() < deadline and self._proc.poll() is None:
                if self.ready_patterns:
                    recent = "\n".join(list(self._log)[-20:])
                    if any(p.search(recent) for p in self.ready_patterns):
                        self._log_line("CLI looks ready")
                        return
                time.sleep(0.1)
            if self._proc.poll() is None:
                self._log_line(
                    f"no ready marker after {ready_timeout_s + extra:.0f}s — "
                    f"configure likely stuck; killing process"
                )
                try:
                    self.stop(2.0)
                except Exception:
                    pass
                tail = "\n    ".join(self._log) or "(no output)"
                raise RuntimeError(
                    f"{self.role} configure did not complete in "
                    f"{ready_timeout_s + extra:.0f}s. "
                    f"Recent output:\n    {tail}"
                )
            rc = self._proc.poll()
            tail = "\n    ".join(self._log) or "(no output)"
            raise RuntimeError(
                f"{self.role} exited with code {rc} during extended startup. "
                f"Recent output:\n    {tail}"
            )
        rc = self._proc.poll()
        tail = "\n    ".join(self._log) or "(no output)"
        raise RuntimeError(
            f"{self.role} exited with code {rc} during startup. "
            f"Recent output:\n    {tail}"
        )

    def _drain_output(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self._log_line(line)
                low = line.lower()
                if any(
                    tok in low
                    for tok in ("traceback", "error:", "permission denied", "not found")
                ):
                    self._last_error = line
        except Exception as exc:
            self._log_line(f"[reader] drain failed: {exc}")

    # ------------------------------------------------------------------
    def stop(self, timeout_s: float = 6.0) -> None:
        """SIGTERM the process group, escalate to SIGKILL after ``timeout_s``.

        lerobot-teleoperate may not run ``finally: robot.disconnect()`` on bare
        SIGTERM, so callers should always follow with motorbridge disable (B601).
        We try SIGINT first so KeyboardInterrupt can unwind the teleop loop.
        """
        proc = self._proc
        if proc is None or proc.poll() is not None:
            self._log_line("already exited" if proc else "not started")
            return
        try:
            pgid = os.getpgid(proc.pid)
            self._log_line(f"SIGINT pgid={pgid}")
            os.killpg(pgid, signal.SIGINT)
        except Exception as exc:
            self._log_line(f"[WARN] SIGINT failed: {exc}")

        t0 = time.time()
        while time.time() - t0 < min(2.0, timeout_s * 0.4):
            if proc.poll() is not None:
                self._log_line(f"exited after SIGINT rc={proc.returncode}")
                return
            time.sleep(0.1)

        try:
            pgid = os.getpgid(proc.pid)
            self._log_line(f"SIGTERM pgid={pgid}")
            os.killpg(pgid, signal.SIGTERM)
        except Exception as exc:
            self._log_line(
                f"[WARN] SIGTERM failed: {exc}; falling back to proc.terminate()"
            )
            try:
                proc.terminate()
            except Exception:
                pass

        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if proc.poll() is not None:
                self._log_line(f"exited cleanly rc={proc.returncode}")
                return
            time.sleep(0.1)

        self._log_line(
            "[WARN] did not exit after SIGTERM — sending SIGKILL "
            "(motors may stay torqued; call /api/b601/disable to recover)"
        )
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def send_stdin(self, text: str = "\n") -> None:
        """Write to subprocess stdin (requires ``keep_stdin_open=True`` on start)."""
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError(f"{self.role} stdin not available")
        proc.stdin.write(text)
        proc.stdin.flush()
        self._log_line(f"stdin: {text!r}")

    def is_alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc else None

    @property
    def returncode(self) -> Optional[int]:
        return self._proc.returncode if self._proc else None
