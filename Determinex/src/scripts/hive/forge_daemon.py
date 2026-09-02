"""
scripts/hive/forge_daemon.py — ForgeDaemon: Autonomous Telemetry Flywheel Trigger
==================================================================================
A file-system watcher embedded in the orchestrator process.  Monitors the
AES-256-GCM encrypted outbox directory written by the Rust telemetry_logger.

When the outbox crosses a configurable threshold (default: 50 encrypted files
OR 10 MB of accumulated payload), ForgeDaemon automatically calls
`determinex_forge.py --auto` in a subprocess — no human intervention required.

The daemon runs as a background polling thread inside the orchestrator process.
No separate daemon process, no OS service.

Patent claim anchor:
  The specific combination of: (1) file-system watcher embedded in orchestrator,
  (2) threshold-triggered autonomous invocation of forge script, (3) AES-256-GCM
  encrypted local telemetry, (4) no cloud transmission — is the "ForgeDaemon"
  described in USPTO provisional application, Invention 2.

Thread safety:
  _triggered: threading.Event — set exactly once per threshold crossing; prevents
  duplicate forge invocations if the forge script is still running.
  _forge_proc: reference held to let callers join or check returncode.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("hive.forge_daemon")

# ── Default thresholds (spec: §Invention 2, ForgeDaemon) ─────────────────────
DEFAULT_THRESHOLD_FILES: int = 50
DEFAULT_THRESHOLD_MB: float = 10.0
DEFAULT_POLL_INTERVAL_S: float = 30.0  # check outbox every 30 seconds

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT = (
    Path(os.environ["DETERMINEX_ROOT"]).resolve()
    if os.environ.get("DETERMINEX_ROOT")
    else Path(__file__).resolve().parent.parent.parent
)
_DEFAULT_OUTBOX = _ROOT / ".determinex_staging" / "outbox"
_DEFAULT_FORGE_PY = _ROOT / "scripts" / "determinex_forge.py"


class ForgeDaemon:
    """
    Autonomous telemetry flywheel trigger.

    Lifecycle::

        daemon = ForgeDaemon()
        daemon.start()          # starts background polling thread
        # ... run_session builds code, Rust backend writes .enc files ...
        daemon.stop()           # signals thread to exit on next poll cycle
        daemon.join(timeout=5)  # wait for clean shutdown

    State machine:
        IDLE → (threshold crossed) → TRIGGERED → forge subprocess running →
        (forge exits) → IDLE (threshold reset) OR TRIGGERED (still over threshold)

    Re-trigger policy:
        After a forge run completes, the daemon re-evaluates the outbox.  If the
        outbox is still over threshold (e.g. new .enc files arrived during the
        forge run), a new forge invocation is launched immediately.  This prevents
        starvation under high-throughput sessions.
    """

    def __init__(
        self,
        outbox_dir: Path = _DEFAULT_OUTBOX,
        forge_script: Path = _DEFAULT_FORGE_PY,
        threshold_files: int = DEFAULT_THRESHOLD_FILES,
        threshold_mb: float = DEFAULT_THRESHOLD_MB,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        python_executable: str = sys.executable,
    ) -> None:
        self.outbox_dir = Path(outbox_dir)
        self.forge_script = Path(forge_script)
        self.threshold_files = threshold_files
        self.threshold_mb = threshold_mb
        self.poll_interval_s = poll_interval_s
        self.python_executable = python_executable

        self._stop_event: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self._forge_proc: subprocess.Popen | None = None
        self._trigger_count: int = 0  # total invocations this session
        self._lock: threading.Lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background polling thread.  Safe to call multiple times."""
        if self._thread and self._thread.is_alive():
            log.debug("ForgeDaemon already running — start() is a no-op")
            return

        if not self.forge_script.exists():
            log.warning(
                "ForgeDaemon: forge script not found at %s — daemon disabled", self.forge_script
            )
            return

        if not self.outbox_dir.exists():
            # Outbox may not exist until the first Vanguard-enabled session
            log.info("ForgeDaemon: outbox does not exist yet — will create on first check")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="ForgeDaemon",
            daemon=True,  # dies with the parent process — no orphaned threads
        )
        self._thread.start()
        log.info(
            "ForgeDaemon started — outbox=%s threshold=%d files / %.1fMB poll=%.0fs",
            self.outbox_dir,
            self.threshold_files,
            self.threshold_mb,
            self.poll_interval_s,
        )

    def stop(self) -> None:
        """Signal the polling thread to exit on its next iteration."""
        self._stop_event.set()
        log.info("ForgeDaemon stop signal sent")

    def join(self, timeout: float = 5.0) -> None:
        """Block until the polling thread exits."""
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def check_and_trigger(self) -> bool:
        """
        Synchronous threshold check — can be called from any thread.
        Returns True if a forge invocation was launched, False if below threshold.
        """
        if not self.outbox_dir.exists():
            return False

        enc_files = list(self.outbox_dir.glob("*.enc"))
        if not enc_files:
            return False

        total_mb = sum(f.stat().st_size for f in enc_files) / 1_000_000

        threshold_crossed = len(enc_files) >= self.threshold_files or total_mb >= self.threshold_mb

        if not threshold_crossed:
            log.debug(
                "ForgeDaemon: outbox below threshold (%d files / %.2fMB — "
                "threshold=%d files / %.1fMB)",
                len(enc_files),
                total_mb,
                self.threshold_files,
                self.threshold_mb,
            )
            return False

        with self._lock:
            # Don't double-trigger while a forge run is still in-flight
            if self._forge_proc and self._forge_proc.poll() is None:
                log.info(
                    "ForgeDaemon: threshold crossed but forge already running "
                    "(pid=%d) — will re-evaluate after it exits",
                    self._forge_proc.pid,
                )
                return False

            log.info(
                "ForgeDaemon: THRESHOLD CROSSED — %d encrypted files / %.2fMB "
                "→ launching forge script",
                len(enc_files),
                total_mb,
            )
            self._trigger_count += 1
            self._forge_proc = subprocess.Popen(
                [self.python_executable, str(self.forge_script), "--auto"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            log.info(
                "ForgeDaemon: forge subprocess launched (pid=%d, trigger #%d)",
                self._forge_proc.pid,
                self._trigger_count,
            )

        # Collect output in a background reader thread so we don't block
        threading.Thread(
            target=self._collect_forge_output,
            args=(self._forge_proc,),
            daemon=True,
        ).start()

        return True

    # ── Internal ──────────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Main loop executed by the daemon thread."""
        log.debug("ForgeDaemon poll loop started")
        while not self._stop_event.is_set():
            try:
                self.check_and_trigger()
            except Exception as exc:
                # Never crash the thread — log and continue
                log.error("ForgeDaemon: unexpected error in poll loop: %s", exc, exc_info=True)

            self._stop_event.wait(timeout=self.poll_interval_s)

        log.debug("ForgeDaemon poll loop exiting")

    # G31: Maximum wall-clock time for a single forge run.  A hung forge script
    # (e.g. waiting for network that isn't there) would otherwise block the
    # daemon thread's re-evaluation loop indefinitely.
    _FORGE_TIMEOUT_S: float = 300.0  # 5 minutes

    def _collect_forge_output(self, proc: subprocess.Popen) -> None:
        """Stream forge subprocess stdout to our logger; enforce a hard timeout."""
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip("\n")
                if line:
                    log.info("  [FORGE] %s", line)
            try:
                proc.wait(timeout=self._FORGE_TIMEOUT_S)  # G31: hard deadline
            except subprocess.TimeoutExpired:
                log.error(
                    "ForgeDaemon: forge subprocess exceeded %.0fs timeout — killing",
                    self._FORGE_TIMEOUT_S,
                )
                proc.kill()
                proc.wait()
            rc = proc.returncode
            if rc == 0:
                log.info("ForgeDaemon: forge subprocess exited OK (rc=0)")
            else:
                log.warning("ForgeDaemon: forge subprocess exited with rc=%d", rc)
        except Exception as exc:
            log.error("ForgeDaemon: output collector error: %s", exc)

    @property
    def trigger_count(self) -> int:
        """Total number of forge invocations this session."""
        return self._trigger_count

    @property
    def is_running(self) -> bool:
        """True while the background polling thread is alive."""
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict:
        """Return a snapshot of daemon state for session logging."""
        with self._lock:
            forge_running = self._forge_proc is not None and self._forge_proc.poll() is None
        return {
            "daemon_running": self.is_running,
            "forge_in_flight": forge_running,
            "trigger_count": self._trigger_count,
            "threshold_files": self.threshold_files,
            "threshold_mb": self.threshold_mb,
            "outbox_dir": str(self.outbox_dir),
        }


# ── Module-level singleton (one daemon per orchestrator process) ───────────────
_daemon: ForgeDaemon | None = None


def get_forge_daemon(
    outbox_dir: Path = _DEFAULT_OUTBOX,
    forge_script: Path = _DEFAULT_FORGE_PY,
    threshold_files: int = DEFAULT_THRESHOLD_FILES,
    threshold_mb: float = DEFAULT_THRESHOLD_MB,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> ForgeDaemon:
    """
    Return the module-level singleton ForgeDaemon, creating it on first call.
    All subsequent calls return the same instance regardless of arguments.

    G32: If called with non-default arguments after the singleton already exists,
    log a warning so callers know their configuration is being silently ignored.
    """
    global _daemon
    if _daemon is None:
        _daemon = ForgeDaemon(
            outbox_dir=outbox_dir,
            forge_script=forge_script,
            threshold_files=threshold_files,
            threshold_mb=threshold_mb,
            poll_interval_s=poll_interval_s,
        )
    else:
        # G32: detect re-init attempts with different config
        _non_default = (
            outbox_dir != _DEFAULT_OUTBOX
            or forge_script != _DEFAULT_FORGE_PY
            or threshold_files != DEFAULT_THRESHOLD_FILES
            or threshold_mb != DEFAULT_THRESHOLD_MB
            or poll_interval_s != DEFAULT_POLL_INTERVAL_S
        )
        if _non_default:
            log.warning(
                "ForgeDaemon: get_forge_daemon() called with non-default arguments "
                "after singleton is already initialised — arguments ignored. "
                "Call stop_forge_daemon() first to replace the singleton."
            )
    return _daemon


def start_forge_daemon(**kwargs) -> ForgeDaemon:
    """Convenience: get singleton and start it if not already running."""
    d = get_forge_daemon(**kwargs)
    if not d.is_running:
        d.start()
    return d


def stop_forge_daemon() -> None:
    """Signal the singleton to stop and wait up to 5s for clean exit."""
    global _daemon
    if _daemon:
        _daemon.stop()
        _daemon.join(timeout=5.0)
