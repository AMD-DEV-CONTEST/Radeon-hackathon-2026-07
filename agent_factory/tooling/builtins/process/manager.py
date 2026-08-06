from __future__ import annotations

import atexit
from dataclasses import dataclass, field
from pathlib import Path
import logging
import os
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, TextIO

from agent_factory.tooling.builtins.process.runtime import ShellRuntime, resolve_shell_runtime
from agent_factory.tooling.workspace_paths import workspace_path_candidate


_OUTPUT_BUFFER_LIMIT = 1_000_000
_DEFAULT_OUTPUT_CHARS = 12_000
_OUTPUT_OBSERVATION_INTERVAL_SECONDS = 0.1
_CANCELLATION_GRACE_SECONDS = 2


ProcessOutputObserver = Callable[[dict[str, Any]], None]
ProcessCancellationCheck = Callable[[], bool]
LOGGER = logging.getLogger(__name__)


class OutputBuffer:
    def __init__(self, *, limit: int = _OUTPUT_BUFFER_LIMIT) -> None:
        self._limit = limit
        self._chunks: list[str] = []
        self._size = 0
        self._truncated = False
        self._lock = threading.RLock()

    def append(self, value: str) -> None:
        if not value:
            return
        with self._lock:
            self._chunks.append(value)
            self._size += len(value)
            while self._size > self._limit and self._chunks:
                removed = self._chunks.pop(0)
                self._size -= len(removed)
                self._truncated = True

    def snapshot(self, *, max_chars: int) -> tuple[str, bool]:
        with self._lock:
            text = "".join(self._chunks)
            truncated = self._truncated
        if len(text) > max_chars:
            text = text[-max_chars:]
            truncated = True
        return text, truncated


@dataclass(slots=True)
class ManagedProcess:
    process_id: str
    command: str
    cwd: Path
    process: subprocess.Popen[str]
    shell_runtime: ShellRuntime
    started_at: float
    stdout: OutputBuffer = field(default_factory=OutputBuffer)
    stderr: OutputBuffer = field(default_factory=OutputBuffer)
    reader_threads: list[threading.Thread] = field(default_factory=list)
    stop_requested: bool = False

    def status(self) -> str:
        exit_code = self.process.poll()
        if exit_code is None:
            return "running"
        if self.stop_requested:
            return "stopped"
        if exit_code == 0:
            return "completed"
        return "failed"


class ProcessManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: dict[str, ManagedProcess] = {}

    def start(
        self,
        *,
        command: str,
        cwd: Path,
        mode: str,
        max_output_chars: int,
        on_output: ProcessOutputObserver | None = None,
        cancellation_requested: ProcessCancellationCheck | None = None,
    ) -> dict[str, Any]:
        process_id = uuid.uuid4().hex
        shell_runtime = resolve_shell_runtime()
        process = subprocess.Popen(
            shell_runtime.command_argv(command),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=shell_runtime.environment(os.environ),
            **shell_runtime.process_options(),
        )
        managed = ManagedProcess(
            process_id=process_id,
            command=command,
            cwd=cwd,
            process=process,
            shell_runtime=shell_runtime,
            started_at=time.monotonic(),
        )
        with self._lock:
            self._processes[process_id] = managed
        output_changed = threading.Event()
        self._start_reader(managed, "stdout", process.stdout, output_changed=output_changed)
        self._start_reader(managed, "stderr", process.stderr, output_changed=output_changed)
        if mode == "foreground":
            self._wait_until_terminal(
                managed,
                max_output_chars=max_output_chars,
                output_changed=output_changed,
                on_output=on_output,
                cancellation_requested=cancellation_requested,
            )
        return self.snapshot(process_id=process_id, max_output_chars=max_output_chars)

    def snapshot(self, *, process_id: str, max_output_chars: int) -> dict[str, Any]:
        managed = self._get(process_id)
        if managed.process.poll() is not None:
            for thread in managed.reader_threads:
                thread.join(timeout=0.05)
        stdout, stdout_truncated = managed.stdout.snapshot(max_chars=max_output_chars)
        stderr, stderr_truncated = managed.stderr.snapshot(max_chars=max_output_chars)
        exit_code = managed.process.poll()
        return {
            "process_id": managed.process_id,
            "status": managed.status(),
            "command": managed.command,
            "shell": managed.shell_runtime.shell_id,
            "shell_executable": str(managed.shell_runtime.executable),
            "cwd": str(managed.cwd),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "duration_ms": int((time.monotonic() - managed.started_at) * 1000),
        }

    def stop(self, *, process_id: str, grace_seconds: int, max_output_chars: int) -> dict[str, Any]:
        managed = self._get(process_id)
        self._terminate(managed, grace_seconds=grace_seconds)
        return self.snapshot(process_id=process_id, max_output_chars=max_output_chars)

    def close(self) -> None:
        with self._lock:
            process_ids = list(self._processes)
        for process_id in process_ids:
            try:
                self.stop(
                    process_id=process_id,
                    grace_seconds=0,
                    max_output_chars=1,
                )
            except (KeyError, OSError, subprocess.SubprocessError):
                continue

    def _get(self, process_id: str) -> ManagedProcess:
        with self._lock:
            try:
                return self._processes[process_id]
            except KeyError as exc:
                raise KeyError(f"unknown process_id: {process_id}") from exc

    def _start_reader(
        self,
        managed: ManagedProcess,
        stream_name: str,
        stream: TextIO | None,
        *,
        output_changed: threading.Event,
    ) -> None:
        if stream is None:
            return
        buffer = managed.stdout if stream_name == "stdout" else managed.stderr
        thread = threading.Thread(
            target=_read_stream,
            args=(stream, buffer, output_changed),
            name=f"tool-{managed.process_id}-{stream_name}",
            daemon=True,
        )
        managed.reader_threads.append(thread)
        thread.start()

    def _wait_until_terminal(
        self,
        managed: ManagedProcess,
        *,
        max_output_chars: int,
        output_changed: threading.Event,
        on_output: ProcessOutputObserver | None,
        cancellation_requested: ProcessCancellationCheck | None,
    ) -> None:
        while managed.process.poll() is None:
            if cancellation_requested is not None and cancellation_requested():
                self._terminate(managed, grace_seconds=_CANCELLATION_GRACE_SECONDS)
                break
            changed = output_changed.wait(timeout=_OUTPUT_OBSERVATION_INTERVAL_SECONDS)
            if changed:
                try:
                    managed.process.wait(timeout=_OUTPUT_OBSERVATION_INTERVAL_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
                output_changed.clear()
                self._notify_output(managed, max_output_chars=max_output_chars, observer=on_output)
        for thread in managed.reader_threads:
            thread.join(timeout=_OUTPUT_OBSERVATION_INTERVAL_SECONDS)
        if output_changed.is_set():
            output_changed.clear()
            self._notify_output(managed, max_output_chars=max_output_chars, observer=on_output)

    def _terminate(self, managed: ManagedProcess, *, grace_seconds: int) -> None:
        managed.stop_requested = True
        if managed.process.poll() is not None:
            return
        managed.shell_runtime.terminate_tree(managed.process)
        try:
            managed.process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            managed.shell_runtime.kill_tree(managed.process)
            managed.process.wait()

    def _notify_output(
        self,
        managed: ManagedProcess,
        *,
        max_output_chars: int,
        observer: ProcessOutputObserver | None,
    ) -> None:
        if observer is None:
            return
        try:
            observer(self.snapshot(process_id=managed.process_id, max_output_chars=max_output_chars))
        except Exception:
            LOGGER.warning("shell output observer failed for process %s", managed.process_id, exc_info=True)


def _read_stream(stream: TextIO, buffer: OutputBuffer, output_changed: threading.Event) -> None:
    try:
        while True:
            chunk = stream.readline()
            if chunk == "":
                break
            buffer.append(chunk)
            output_changed.set()
    finally:
        stream.close()


PROCESS_MANAGER = ProcessManager()
atexit.register(PROCESS_MANAGER.close)


def process_runtime_boundary(resources: dict[str, Any]) -> tuple[Path, bool]:
    config = resources.get("process_runtime", {})
    if isinstance(config, str):
        root_value: Any = config
        allow_external = False
    elif isinstance(config, dict):
        root_value = config.get("root") or config.get("cwd") or "."
        allow_external = bool(config.get("allow_external", False))
    else:
        root_value = "."
        allow_external = False
    return Path(str(root_value)).expanduser().resolve(), allow_external


def process_runtime_allowed_roots(resources: dict[str, Any]) -> tuple[Path, ...]:
    config = resources.get("process_runtime", {})
    values = config.get("allowed_roots", []) if isinstance(config, dict) else []
    if not isinstance(values, list):
        return ()
    return tuple(
        Path(value).expanduser().resolve(strict=False)
        for value in values
        if isinstance(value, str) and value.strip()
    )


def resolve_cwd(
    *,
    cwd: str | None,
    root: Path,
    allow_external: bool,
    allowed_roots: tuple[Path, ...] = (),
) -> Path:
    value = cwd if cwd is not None and cwd.strip() else "."
    candidate = workspace_path_candidate(value, root=root)
    resolved = candidate.resolve(strict=False)
    if allow_external:
        return resolved
    for allowed_root in (root, *allowed_roots):
        try:
            resolved.relative_to(allowed_root)
            return resolved
        except ValueError:
            continue
    raise ValueError(f"cwd escapes process runtime root: {value}")


def is_read_only_process_path(path: Path, *, root: Path, resources: dict[str, Any]) -> bool:
    config = resources.get("process_runtime", {})
    values = config.get("read_only_paths", []) if isinstance(config, dict) else []
    if not isinstance(values, list):
        return False
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        requested = Path(value).expanduser()
        candidate = requested if requested.is_absolute() else root / requested
        resolved = candidate.resolve(strict=False)
        if path == resolved or resolved in path.parents:
            return True
    return False


def required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def bounded_int(arguments: dict[str, Any], key: str, *, default: int, minimum: int, maximum: int) -> int:
    value = arguments.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def output_limit(arguments: dict[str, Any]) -> int:
    return bounded_int(arguments, "max_output_chars", default=_DEFAULT_OUTPUT_CHARS, minimum=1, maximum=200_000)
