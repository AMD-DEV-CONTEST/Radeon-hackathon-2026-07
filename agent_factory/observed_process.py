from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import queue
import subprocess
import threading
import time


ProcessOutputObserver = Callable[[str, str], None]


class ObservedProcessCancelled(RuntimeError):
    pass


class ObservedProcessInactivityTimeout(subprocess.TimeoutExpired):
    pass


@dataclass(frozen=True, slots=True)
class ObservedProcessResult:
    returncode: int
    stdout: str
    stderr: str


def run_observed_process(
    command: Sequence[str],
    *,
    input_text: str | None = None,
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    inactivity_timeout_seconds: float | None = None,
    on_output: ProcessOutputObserver | None = None,
    cancel_event: threading.Event | None = None,
) -> ObservedProcessResult:
    """Run a subprocess while collecting and forwarding stdout/stderr lines."""
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=dict(environment) if environment is not None else None,
    )
    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    readers = [
        threading.Thread(
            target=_read_stream,
            args=(stream_name, stream, output_queue),
            daemon=True,
        )
        for stream_name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
        if stream is not None
    ]
    for reader in readers:
        reader.start()
    if input_text is not None and process.stdin is not None:
        try:
            process.stdin.write(input_text)
            process.stdin.flush()
        finally:
            process.stdin.close()

    started_at = time.monotonic()
    last_output_at = started_at
    completed_streams = 0
    captured: dict[str, list[str]] = {"stdout": [], "stderr": []}
    try:
        while completed_streams < len(readers) or process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                raise ObservedProcessCancelled("subprocess execution was cancelled")
            elapsed = time.monotonic() - started_at
            if timeout_seconds is not None and elapsed >= timeout_seconds:
                raise subprocess.TimeoutExpired(
                    list(command),
                    timeout_seconds,
                    output="".join(captured["stdout"]),
                    stderr="".join(captured["stderr"]),
                )
            inactive_for = time.monotonic() - last_output_at
            if (
                inactivity_timeout_seconds is not None
                and inactive_for >= inactivity_timeout_seconds
            ):
                raise ObservedProcessInactivityTimeout(
                    list(command),
                    inactivity_timeout_seconds,
                    output="".join(captured["stdout"]),
                    stderr="".join(captured["stderr"]),
                )
            remaining_deadlines = [
                value
                for value in (
                    timeout_seconds - elapsed if timeout_seconds is not None else None,
                    inactivity_timeout_seconds - inactive_for
                    if inactivity_timeout_seconds is not None
                    else None,
                )
                if value is not None
            ]
            wait_seconds = (
                min(0.1, max(min(remaining_deadlines), 0.001))
                if remaining_deadlines
                else 0.1
            )
            try:
                stream_name, line = output_queue.get(timeout=wait_seconds)
            except queue.Empty:
                continue
            if line is None:
                completed_streams += 1
                continue
            captured[stream_name].append(line)
            last_output_at = time.monotonic()
            if on_output is not None:
                on_output(stream_name, line)
    except (subprocess.TimeoutExpired, ObservedProcessCancelled) as exc:
        _stop_process(process)
        _drain_output(output_queue, captured)
        if cancel_event is not None and cancel_event.is_set():
            raise ObservedProcessCancelled("subprocess execution was cancelled") from None
        if isinstance(exc, ObservedProcessInactivityTimeout):
            raise ObservedProcessInactivityTimeout(
                list(command),
                inactivity_timeout_seconds,
                output="".join(captured["stdout"]),
                stderr="".join(captured["stderr"]),
            ) from None
        raise subprocess.TimeoutExpired(
            list(command),
            timeout_seconds,
            output="".join(captured["stdout"]),
            stderr="".join(captured["stderr"]),
        ) from None
    finally:
        for reader in readers:
            reader.join(timeout=1)
        if process.poll() is None:
            _stop_process(process)

    return ObservedProcessResult(
        returncode=process.wait(),
        stdout="".join(captured["stdout"]),
        stderr="".join(captured["stderr"]),
    )


def _read_stream(
    stream_name: str,
    stream: object,
    output_queue: queue.Queue[tuple[str, str | None]],
) -> None:
    try:
        readline = getattr(stream, "readline")
        while True:
            line = readline()
            if line == "":
                break
            output_queue.put((stream_name, line))
    finally:
        output_queue.put((stream_name, None))
        close = getattr(stream, "close", None)
        if callable(close):
            close()


def _drain_output(
    output_queue: queue.Queue[tuple[str, str | None]],
    captured: dict[str, list[str]],
) -> None:
    while True:
        try:
            stream_name, line = output_queue.get_nowait()
        except queue.Empty:
            return
        if line is not None:
            captured[stream_name].append(line)


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
