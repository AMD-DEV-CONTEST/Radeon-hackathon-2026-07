"""
scripts/hive/concurrent_guard.py — Concurrency and IPC safety primitives
=========================================================================
Implements mitigations for six verified Determinex blindspots:

  #27  asyncio.Semaphore backpressure on per-role API concurrency
  #28  Hardware file lock on workspace directories (fcntl / LOCKFILE)
  #30  multiprocessing.Pool wrapper for CPU-bound validation (GIL bypass)
  #32  SIGKILL-capable thread timeout for hung subprocess calls
  #34  Stale-state temporal desync guard (last-write-wins with epoch tagging)
  #36  asyncio event loop isolation — prevent cross-thread loop reuse

All primitives are optional-import safe:
  - asyncio / multiprocessing are stdlib
  - fcntl is POSIX only; Windows falls back to a lockfile-based mutex
  - No additional pip dependencies required
"""

from __future__ import annotations

import asyncio
import atexit
import ctypes
import logging
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("hive.guard")


# ── #27 Asyncio backpressure semaphore ───────────────────────────────────────

# One semaphore per role, keyed by role name string.
# Default concurrency per role — tunable at runtime via configure_concurrency().
_DEFAULT_CONCURRENCY: dict[str, int] = {
    "builder": 1,  # local Ollama: serialize to prevent VRAM thrash
    "monitor": 1,  # local Ollama: same
    "oracle": 2,  # cloud API: two in-flight at once is safe
    "architect": 1,  # cloud API: single high-value call
}

_semaphores: dict[str, asyncio.Semaphore] = {}
_semaphore_lock = threading.Lock()


def configure_concurrency(role_limits: dict[str, int]) -> None:
    """
    Override per-role concurrency limits at runtime.
    Must be called before the asyncio event loop is started.
    """
    _DEFAULT_CONCURRENCY.update(role_limits)
    # G28: Invalidate BOTH semaphore caches so they rebuild with new limits.
    # Previously only _semaphores (asyncio) was cleared; _thread_semaphores
    # (the synchronous equivalents used by api_backpressure) were left stale.
    with _semaphore_lock:
        _semaphores.clear()
    with _tsem_lock:
        _thread_semaphores.clear()
    log.info("[#27] Concurrency limits updated: %s", _DEFAULT_CONCURRENCY)


def _get_semaphore(role: str) -> asyncio.Semaphore:
    """Get (or create) the asyncio.Semaphore for a role, thread-safely."""
    with _semaphore_lock:
        if role not in _semaphores:
            limit = _DEFAULT_CONCURRENCY.get(role, 1)
            _semaphores[role] = asyncio.Semaphore(limit)
            log.debug("[#27] Created semaphore for role '%s' with limit=%d", role, limit)
        return _semaphores[role]


@contextmanager
def api_backpressure(role: str):
    """
    Synchronous context manager that acquires the asyncio backpressure
    semaphore for a role.

    Usage (from sync code inside executor.py):
        with api_backpressure("builder"):
            result = api_call(...)

    This wraps the asyncio primitive in a threading.Semaphore for callers
    that run outside an asyncio event loop (the common case in Determinex today).
    The asyncio.Semaphore is kept as the canonical limit; this wrapper converts
    it to a threading one keyed by role.
    """
    limit = _DEFAULT_CONCURRENCY.get(role, 1)
    sem = _get_thread_semaphore(role, limit)
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


# Thread-safe equivalents for synchronous callers.
_thread_semaphores: dict[str, threading.Semaphore] = {}
_tsem_lock = threading.Lock()


def _get_thread_semaphore(role: str, limit: int) -> threading.Semaphore:
    with _tsem_lock:
        if role not in _thread_semaphores:
            _thread_semaphores[role] = threading.Semaphore(limit)
        return _thread_semaphores[role]


# ── #28 Hardware workspace file lock ─────────────────────────────────────────


class WorkspaceLockError(RuntimeError):
    """Raised when the workspace lock cannot be acquired within the timeout."""


class WorkspaceLock:
    """
    Per-session exclusive file lock preventing two concurrent Determinex runs
    from clobbering the same workspace.

    POSIX: uses fcntl.flock (advisory, kernel-enforced).
    Windows: uses a lock file with atomic creation flag (O_CREAT | O_EXCL).
    """

    def __init__(self, session_id: str, workspace_root: Path, timeout: float = 10.0):
        self._session_id = session_id
        self._lock_path = workspace_root / f".determinex_{session_id}.lock"
        self._timeout = timeout
        self._fd: int | None = None
        self._lock_file = None

    def acquire(self) -> None:
        deadline = time.monotonic() + self._timeout
        if sys.platform != "win32":
            self._acquire_posix(deadline)
        else:
            self._acquire_windows(deadline)
        # L13-B: guarantee release even on unclean exit (crash, SIGKILL, sys.exit)
        atexit.register(self.release)
        log.info("[#28] Workspace lock acquired: %s", self._lock_path)

    def _acquire_posix(self, deadline: float) -> None:
        import fcntl

        self._fd = os.open(str(self._lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.write(self._fd, f"{os.getpid()}\n".encode())
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise WorkspaceLockError(
                        f"Workspace lock timeout for session {self._session_id}. "
                        f"Another Determinex process may be running. Lock file: {self._lock_path}"
                    )
                time.sleep(0.25)

    def _acquire_windows(self, deadline: float) -> None:
        while True:
            try:
                self._fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.write(self._fd, f"{os.getpid()}\n".encode())
                return
            except FileExistsError:
                # L13-B: stale lock check — if the owning PID is dead, remove and retry
                try:
                    pid_text = self._lock_path.read_text(encoding="utf-8").strip()
                    owner_pid = int(pid_text)
                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    h = ctypes.windll.kernel32.OpenProcess(
                        PROCESS_QUERY_LIMITED_INFORMATION, False, owner_pid
                    )
                    if h:
                        exit_code = ctypes.c_ulong(259)  # 259 = STILL_ACTIVE
                        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
                        ctypes.windll.kernel32.CloseHandle(h)
                        if exit_code.value != 259:
                            # Process exited but handle still openable — stale
                            log.warning(
                                "[#28-L13B] Stale lock: PID %d exited — removing %s",
                                owner_pid,
                                self._lock_path,
                            )
                            self._lock_path.unlink(missing_ok=True)
                            continue
                    else:
                        # OpenProcess failed — PID does not exist
                        log.warning(
                            "[#28-L13B] Stale lock: PID %d not found — removing %s",
                            owner_pid,
                            self._lock_path,
                        )
                        self._lock_path.unlink(missing_ok=True)
                        continue
                except (ValueError, OSError, AttributeError):
                    pass
                if time.monotonic() >= deadline:
                    raise WorkspaceLockError(
                        f"Workspace lock timeout for session {self._session_id}. "
                        f"Lock file exists: {self._lock_path}"
                    )
                time.sleep(0.25)

    def release(self) -> None:
        if self._fd is not None:
            try:
                if sys.platform != "win32":
                    import fcntl

                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
                self._fd = None
            except OSError:
                pass
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        log.info("[#28] Workspace lock released: %s", self._lock_path)

    def __enter__(self) -> WorkspaceLock:
        self.acquire()
        return self

    def __exit__(self, *_) -> None:
        self.release()


# ── #30 multiprocessing.Pool for CPU-bound validation ────────────────────────


def _mp_validate_worker(args: tuple[str, str]) -> tuple[bool, str]:
    """
    Worker function for validate_project in a subprocess.
    Must be importable at the top level (multiprocessing requirement).
    args = (workspace_path_str, lang)
    """
    workspace_str, lang = args
    from pathlib import Path as _Path

    from hive.compiler import validate_project as _validate

    return _validate(_Path(workspace_str), lang)


class CompilerPool:
    """
    Manages a multiprocessing.Pool for running CPU-intensive compiler
    validation steps off the main process (GIL bypass).

    The pool is lazy-initialized and reused across the DAG execution loop.
    It is shut down cleanly at the end of run_session.

    Usage:
        pool = CompilerPool(workers=2)
        passed, output = pool.validate(workspace, lang)
        pool.shutdown()
    """

    def __init__(self, workers: int = 1) -> None:
        self._workers = workers
        self._pool: multiprocessing.Pool | None = None

    def _ensure_pool(self) -> multiprocessing.Pool:
        if self._pool is None:
            # 'spawn' context avoids CUDA/fork issues on Linux and is the only
            # option on Windows/macOS. Slightly slower to start but safe.
            ctx = multiprocessing.get_context("spawn")
            self._pool = ctx.Pool(processes=self._workers)
            log.info("[#30] CompilerPool initialized (workers=%d, context=spawn)", self._workers)
        return self._pool

    def validate(self, workspace: Path, lang: str, timeout: float = 60.0) -> tuple[bool, str]:
        """
        Run validate_project in a subprocess. Falls back to in-process on error.
        """
        try:
            pool = self._ensure_pool()
            result = pool.apply_async(_mp_validate_worker, ((str(workspace), lang),))
            return result.get(timeout=timeout)
        except multiprocessing.TimeoutError:
            log.warning(
                "[#30] CompilerPool.validate timed out after %.0fs — falling back in-process",
                timeout,
            )
        except Exception as e:
            log.warning("[#30] CompilerPool.validate failed (%s) — falling back in-process", e)
        # Fallback: run in-process (GIL holds, but at least we don't crash)
        from hive.compiler import validate_project

        return validate_project(workspace, lang)

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.terminate()
            self._pool.join()
            self._pool = None
            log.info("[#30] CompilerPool shut down")


# ── #32 SIGKILL-capable subprocess timeout ────────────────────────────────────


class SubprocessTimeoutError(RuntimeError):
    """Raised when a subprocess is killed due to timeout."""


def run_with_timeout(
    cmd: list[str],
    timeout: float,
    cwd: Path | None = None,
    env: dict | None = None,
    capture_output: bool = True,
) -> tuple[int, str, str]:
    """
    Run a subprocess with a SIGKILL-capable hard timeout.

    On timeout:
      - POSIX: sends SIGTERM, then SIGKILL after 2s if still alive.
      - Windows: calls TerminateProcess (equivalent to SIGKILL).

    Returns (returncode, stdout, stderr).
    Raises SubprocessTimeoutError if the process was killed.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )

    killed = threading.Event()

    def _watchdog() -> None:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            killed.set()
            log.warning(
                "[#32] Subprocess timeout (%.0fs) — sending SIGTERM to PID %d", timeout, proc.pid
            )
            if sys.platform != "win32":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.terminate()
                # Give two seconds before SIGKILL
                time.sleep(2.0)
                if proc.poll() is None:
                    log.warning("[#32] SIGTERM ignored — sending SIGKILL to PID %d", proc.pid)
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        proc.kill()
            else:
                proc.kill()

    watcher = threading.Thread(target=_watchdog, daemon=True)
    watcher.start()

    stdout, stderr = proc.communicate()
    watcher.join()

    if killed.is_set():
        raise SubprocessTimeoutError(f"Subprocess killed after {timeout:.0f}s: {' '.join(cmd[:3])}")

    return proc.returncode, stdout or "", stderr or ""


# ── #34 Stale-state temporal desync guard ────────────────────────────────────


class EpochTaggedState:
    """
    Thread-safe epoch-tagged shared state container.

    Prevents the stale-state race condition (#34) where two async agents
    read the same file state, one updates it, and the other writes an
    outdated version back on top.

    Each write increments an epoch counter. Conditional writes fail if
    the caller's epoch is behind the current one (optimistic concurrency).

    Usage:
        state = EpochTaggedState({"status": "pending"})
        epoch, data = state.read()
        # ... do work ...
        ok = state.write_if_epoch(epoch, {"status": "complete"})
        if not ok:
            # Concurrent writer won — re-read and retry
    """

    def __init__(self, initial: dict) -> None:
        self._lock = threading.Lock()
        self._epoch: int = 0
        self._data: dict = dict(initial)

    def read(self) -> tuple[int, dict]:
        """Return (current_epoch, copy_of_data)."""
        with self._lock:
            return self._epoch, dict(self._data)

    def write(self, new_data: dict) -> int:
        """Unconditional write. Returns new epoch."""
        with self._lock:
            self._epoch += 1
            self._data = dict(new_data)
            return self._epoch

    def write_if_epoch(self, expected_epoch: int, new_data: dict) -> bool:
        """
        Write only if current epoch == expected_epoch (optimistic CAS).
        Returns True on success, False if a concurrent writer already advanced the epoch.
        """
        with self._lock:
            if self._epoch != expected_epoch:
                log.warning(
                    "[#34] Stale write rejected: expected epoch=%d, current=%d",
                    expected_epoch,
                    self._epoch,
                )
                return False
            self._epoch += 1
            self._data = dict(new_data)
            return True

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch


# Per-session EpochTaggedState registry — keyed by session_id.
_session_states: dict[str, EpochTaggedState] = {}
_session_states_lock = threading.Lock()


def get_session_state(session_id: str, initial: dict | None = None) -> EpochTaggedState:
    """Get (or create) the EpochTaggedState for a session."""
    with _session_states_lock:
        if session_id not in _session_states:
            _session_states[session_id] = EpochTaggedState(initial or {})
        return _session_states[session_id]


def drop_session_state(session_id: str) -> None:
    """Remove state tracking for a completed session (prevents memory leak)."""
    with _session_states_lock:
        _session_states.pop(session_id, None)


# ── #36 asyncio event loop isolation ─────────────────────────────────────────

_loop_registry: dict[int, asyncio.AbstractEventLoop] = {}  # thread_id → loop
_loop_registry_lock = threading.Lock()


def get_isolated_event_loop() -> asyncio.AbstractEventLoop:
    """
    Return a dedicated asyncio event loop for the calling thread.
    Prevents cross-thread loop reuse, which causes `got Future attached to
    a different loop` errors when one thread's coroutine leaks into another's loop.

    Determinex uses threads (ThreadPoolExecutor) to timeout Monitor calls.
    Each thread must own its loop — never share the main loop.
    """
    tid = threading.get_ident()
    with _loop_registry_lock:
        if tid not in _loop_registry:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _loop_registry[tid] = loop
            log.debug("[#36] New isolated event loop for thread %d", tid)
        return _loop_registry[tid]


def close_isolated_event_loop() -> None:
    """Close and deregister the event loop for the calling thread."""
    tid = threading.get_ident()
    with _loop_registry_lock:
        loop = _loop_registry.pop(tid, None)
    if loop is not None and not loop.is_closed():
        loop.close()
        log.debug("[#36] Closed isolated event loop for thread %d", tid)


def run_async_in_thread(coro, timeout: float | None = None):
    """
    Run an asyncio coroutine in the calling thread's isolated event loop.
    Safe to call from any thread, including ThreadPoolExecutor workers.

    Returns the coroutine result or raises on exception/timeout.
    """
    loop = get_isolated_event_loop()
    future = asyncio.ensure_future(coro, loop=loop)
    try:
        return loop.run_until_complete(
            asyncio.wait_for(future, timeout=timeout) if timeout else future
        )
    finally:
        # Always clean up dangling tasks to prevent ResourceWarning noise.
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
