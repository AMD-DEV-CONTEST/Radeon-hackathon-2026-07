"""Replayable contracts for local external solver processes.

This module verifies the program that is executed.  It deliberately does not
claim network isolation: callers that need it must supply an OS/container
sandbox with an enforced network policy.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import threading
import time
from typing import Optional


class AdapterPreflightError(RuntimeError):
    pass


class SolverRunError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class SolverConfiguration:
    name: str
    version: str
    scientific_translation: bool = False


@dataclass(frozen=True)
class ExternalSolverManifest:
    executable: Path
    executable_sha256: str
    version: str
    command: tuple[str, ...]
    working_directory: Path
    database: Optional[Path] = None
    database_sha256: Optional[str] = None
    input_files: tuple[tuple[Path, str], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "executable", Path(self.executable))
        object.__setattr__(self, "working_directory", Path(self.working_directory))
        if self.database is not None:
            object.__setattr__(self, "database", Path(self.database))
        object.__setattr__(self, "input_files", tuple((Path(p), d) for p, d in self.input_files))
        if not self.version or not self.command:
            raise ValueError("version and command are required")
        if any(not isinstance(token, str) or not token for token in self.command):
            raise ValueError("command tokens must be non-empty strings")
        for digest in (self.executable_sha256, self.database_sha256, *(d for _, d in self.input_files)):
            if digest is not None and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower())):
                raise ValueError("manifest hashes must be SHA-256 hex digests")


@dataclass(frozen=True)
class SolverRunResult:
    command: tuple[str, ...]
    exit_status: Optional[int]
    stdout: str
    stderr: str
    stdout_sha256: str
    stderr_sha256: str
    timed_out: bool = False
    duration_seconds: float = 0.0
    launch_error: Optional[str] = None
    timeout_escalated_to_sigkill: bool = False
    stdout_bytes_observed: int = 0
    stderr_bytes_observed: int = 0
    stdout_bytes_retained: int = 0
    stderr_bytes_retained: int = 0
    output_limits_exceeded: tuple[str, ...] = ()
    streams_complete: bool = True
    stream_drain_timed_out: bool = False
    stream_errors: tuple[str, ...] = ()

    @property
    def output_limit_exceeded(self) -> Optional[str]:
        """Backward-compatible first exceeded stream, if any."""
        return self.output_limits_exceeded[0] if self.output_limits_exceeded else None


def _check_path(path: Path, root: Path, label: str) -> None:
    if not path.is_absolute():
        raise AdapterPreflightError(f"{label} path must be absolute")
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise AdapterPreflightError(f"{label} unavailable: {path}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as e:
        raise AdapterPreflightError(f"{label} escapes working directory") from e


def preflight(manifest: ExternalSolverManifest) -> None:
    root = manifest.working_directory
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise AdapterPreflightError("working directory unavailable")
    _check_path(manifest.executable, root, "executable")
    command_executable = Path(manifest.command[0])
    if not command_executable.is_absolute() or command_executable.resolve() != manifest.executable.resolve():
        raise AdapterPreflightError("command must directly execute the hashed executable by absolute path")
    if manifest.database is not None:
        _check_path(manifest.database, root, "database")
    for path, _ in manifest.input_files:
        _check_path(path, root, "input")
    if _sha256(manifest.executable) != manifest.executable_sha256:
        raise AdapterPreflightError("executable SHA-256 mismatch")
    if manifest.database is not None and _sha256(manifest.database) != manifest.database_sha256:
        raise AdapterPreflightError("database SHA-256 mismatch")
    for path, digest in manifest.input_files:
        if _sha256(path) != digest:
            raise AdapterPreflightError(f"input SHA-256 mismatch: {path}")


def _terminate_process(process: subprocess.Popen, *, deadline: float | None = None,
                       grace_seconds: float = 0.5) -> bool:
    """Terminate a timed-out process and collect its pipes.

    POSIX children start in a dedicated session, so signals cover every process
    that remains in the solver's process group.  Other platforms can only rely
    on ``terminate``/``kill`` for the directly created process.  ``deadline``
    is absolute and shared with the caller's execution/drain deadline; no
    reap operation is allowed to wait beyond it.
    """
    if deadline is None:
        deadline = time.monotonic() + grace_seconds

    def wait_bounded() -> bool:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # poll() is non-blocking and reaps the leader when it has already
            # exited, while preserving the caller's deadline otherwise.
            return process.poll() is not None
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            return False
        return True

    escalated = False
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:
        process.terminate()
    if not wait_bounded():
        escalated = True
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        # SIGKILL normally makes the leader reapable immediately.  If it does
        # not, wait_bounded() returns at the shared deadline instead of
        # blocking the qualification call indefinitely.
        wait_bounded()
    else:
        # The leader may have exited while descendants in its group remain.
        if os.name == "posix":
            while time.monotonic() < deadline:
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            else:
                escalated = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    # The leader is reaped when it exits before the shared deadline. Descendants
    # that stay in the dedicated POSIX group have now received TERM or KILL.
    return escalated


def run_replayable(manifest: ExternalSolverManifest, *, timeout: float = 30.0,
                   max_stdout_bytes: int = 1024 * 1024,
                   max_stderr_bytes: int = 1024 * 1024) -> SolverRunResult:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive finite")
    for name, limit in (("max_stdout_bytes", max_stdout_bytes), ("max_stderr_bytes", max_stderr_bytes)):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(f"{name} must be a positive integer")
    preflight(manifest)
    environment = {"HOME": str(manifest.working_directory), "LANG": "C", "LC_ALL": "C", "PATH": os.defpath}
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            manifest.command,
            cwd=manifest.working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        duration = time.monotonic() - started
        return SolverRunResult(manifest.command, None, "", "", hashlib.sha256(b"").hexdigest(),
                               hashlib.sha256(b"").hexdigest(), False, duration,
                               f"{type(exc).__name__}: {exc}", False)
    streams = {
        "stdout": {"pipe": process.stdout, "limit": max_stdout_bytes, "data": bytearray(),
                   "digest": hashlib.sha256(), "observed": 0},
        "stderr": {"pipe": process.stderr, "limit": max_stderr_bytes, "data": bytearray(),
                   "digest": hashlib.sha256(), "observed": 0},
    }
    timed_out = False
    escalated = False
    deadline = started + timeout
    drain_timed_out = False
    stream_errors: list[str] = []

    def record_chunk(state, chunk):
        state["observed"] += len(chunk)
        state["digest"].update(chunk)
        remaining = state["limit"] - len(state["data"])
        if remaining > 0:
            state["data"].extend(chunk[:remaining])

    if os.name == "posix":
        # POSIX pipes are drained without reader threads. The same monotonic
        # deadline covers leader execution and inherited pipe writers.
        selector = selectors.DefaultSelector()
        try:
            for name, state in streams.items():
                os.set_blocking(state["pipe"].fileno(), False)
                selector.register(state["pipe"], selectors.EVENT_READ, name)

            def drain_events(events):
                for key, _ in events:
                    state = streams[key.data]
                    try:
                        while True:
                            chunk = os.read(key.fileobj.fileno(), 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                key.fileobj.close()
                                break
                            record_chunk(state, chunk)
                    except BlockingIOError:
                        pass
                    except OSError as exc:
                        stream_errors.append(f"{key.data}: {type(exc).__name__}: {exc}")
                        try:
                            selector.unregister(key.fileobj)
                        except Exception:
                            pass
                        key.fileobj.close()

            termination_requested = False
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                exceeded_now = any(state["observed"] > state["limit"]
                                   for state in streams.values())
                if exceeded_now and process.poll() is None and not termination_requested:
                    # Capture bytes already becoming readable on the peer pipe
                    # before terminating the group, preserving simultaneous
                    # overflow evidence without allowing unbounded output.
                    drain_events(selector.select(min(0.01, max(0.0, deadline - now))))
                    escalated = _terminate_process(process, deadline=deadline)
                    termination_requested = True
                if now >= deadline:
                    if process.poll() is None:
                        timed_out = True
                        escalated = _terminate_process(process, deadline=deadline) or escalated
                    if selector.get_map():
                        drain_timed_out = True
                        # The leader may already be reaped while descendants in
                        # its original group still own pipe writers.
                        escalated = _terminate_process(process, deadline=deadline) or escalated
                    break
                events = selector.select(min(0.005, deadline - now))
                drain_events(events)
            # Never wait for escaped writers. Closing our read descriptors
            # unblocks the qualification call but does not claim to kill them.
            for key in list(selector.get_map().values()):
                try:
                    selector.unregister(key.fileobj)
                finally:
                    key.fileobj.close()
        finally:
            selector.close()
    else:
        # Non-POSIX fallback retains threads but bounds their join by the same
        # deadline. Platform process-tree containment is not claimed.
        exceeded = threading.Event()

        def read_stream(name, state):
            try:
                while chunk := os.read(state["pipe"].fileno(), 65536):
                    record_chunk(state, chunk)
                    if state["observed"] > state["limit"]:
                        exceeded.set()
            except OSError as exc:
                stream_errors.append(f"{name}: {type(exc).__name__}: {exc}")

        readers = [threading.Thread(target=read_stream, args=(name, state), daemon=True)
                   for name, state in streams.items()]
        for reader in readers:
            reader.start()
        while process.poll() is None and time.monotonic() < deadline and not exceeded.is_set():
            time.sleep(0.005)
        if process.poll() is None:
            timed_out = time.monotonic() >= deadline
            escalated = _terminate_process(process, deadline=deadline)
        for reader in readers:
            reader.join(max(0.0, deadline - time.monotonic()))
        if any(reader.is_alive() for reader in readers):
            drain_timed_out = True
            for state in streams.values():
                state["pipe"].close()
    stdout_state, stderr_state = streams["stdout"], streams["stderr"]
    # A fast process can exit before the monitor observes the reader event.
    # Completed counters are therefore the authoritative overflow evidence.
    exceeded_streams = tuple(
        name for name in ("stdout", "stderr")
        if streams[name]["observed"] > streams[name]["limit"]
    )
    stdout_bytes = bytes(stdout_state["data"])
    stderr_bytes = bytes(stderr_state["data"])
    streams_complete = not drain_timed_out and not stream_errors
    status = None if timed_out or exceeded_streams or not streams_complete else process.returncode
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    duration = time.monotonic() - started
    return SolverRunResult(
        manifest.command,
        status,
        stdout,
        stderr,
        stdout_state["digest"].hexdigest(),
        stderr_state["digest"].hexdigest(),
        timed_out,
        duration,
        None,
        escalated,
        stdout_state["observed"], stderr_state["observed"],
        len(stdout_bytes), len(stderr_bytes), exceeded_streams,
        streams_complete, drain_timed_out, tuple(stream_errors),
    )


class GroundwaterSolverAdapter:
    def __init__(self, manifest: ExternalSolverManifest):
        self.manifest = manifest

    def preflight(self) -> None:
        preflight(self.manifest)

    def run(self, *, timeout: float = 30.0) -> SolverRunResult:
        return run_replayable(self.manifest, timeout=timeout)


class PhreeqcAdapter(GroundwaterSolverAdapter):
    @staticmethod
    def configuration() -> SolverConfiguration:
        return SolverConfiguration("phreeqc", "external", False)
