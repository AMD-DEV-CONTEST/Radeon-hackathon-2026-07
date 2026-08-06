"""Tamper-evident traces proving which GPU output drove each command."""

from __future__ import annotations

import hashlib
import json
import queue
import statistics
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np


def array_sha256(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode())
    digest.update(str(array.shape).encode())
    digest.update(memoryview(array))
    return digest.hexdigest()


def gpu_identity(device_index: int = 0) -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available() or torch.version.hip is None:
        raise RuntimeError("ROCm GPU is required; CPU/CUDA fallback is forbidden")
    properties = torch.cuda.get_device_properties(device_index)
    return {
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "device_index": device_index,
        "device_name": torch.cuda.get_device_name(device_index),
        "total_vram_bytes": int(properties.total_memory),
    }


@dataclass(frozen=True)
class TimingSummary:
    samples: int
    p50_ms: float
    p95_ms: float
    mean_ms: float
    maximum_ms: float

    @classmethod
    def from_values(cls, values: list[float]) -> "TimingSummary":
        if not values:
            raise ValueError("at least one timing sample is required")
        ordered = sorted(values)
        p95_index = min(len(ordered) - 1, int(np.ceil(0.95 * len(ordered))) - 1)
        return cls(
            samples=len(values),
            p50_ms=float(statistics.median(ordered)),
            p95_ms=float(ordered[p95_index]),
            mean_ms=float(statistics.fmean(ordered)),
            maximum_ms=float(max(ordered)),
        )


def benchmark_gpu(
    function: Callable[[], Any],
    *,
    warmup: int = 5,
    repetitions: int = 20,
    device_index: int = 0,
) -> tuple[Any, TimingSummary]:
    """Time completed ROCm work, not asynchronous kernel launches."""

    import torch

    gpu_identity(device_index)
    with torch.inference_mode():
        for _ in range(warmup):
            result = function()
        torch.cuda.synchronize(device_index)
        values: list[float] = []
        for _ in range(repetitions):
            torch.cuda.synchronize(device_index)
            start = time.perf_counter_ns()
            result = function()
            torch.cuda.synchronize(device_index)
            values.append((time.perf_counter_ns() - start) / 1_000_000.0)
    return result, TimingSummary.from_values(values)


class TraceWriter:
    """Append-only JSONL with a SHA256 chain and separate raw tensor files."""

    def __init__(self, output: Path, *, asynchronous: bool = True) -> None:
        self.output = Path(output)
        self.raw_output = self.output / "raw"
        self.output.mkdir(parents=True, exist_ok=True)
        self.raw_output.mkdir(parents=True, exist_ok=True)
        self.path = self.output / "inference.jsonl"
        self._previous = "0" * 64
        self._lock = threading.Lock()
        self._asynchronous = asynchronous
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=256)
        self._error: BaseException | None = None
        self._closed = False
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._previous = json.loads(line)["record_sha256"]
        self._thread = None
        if asynchronous:
            self._thread = threading.Thread(
                target=self._worker,
                name="realtime-trace-writer",
                daemon=True,
            )
            self._thread.start()

    def write(
        self,
        *,
        kind: str,
        model: dict[str, Any],
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        timing: dict[str, Any],
        raw_arrays: dict[str, np.ndarray] | None = None,
        trace_id: str | None = None,
    ) -> str:
        trace_id = trace_id or uuid.uuid4().hex
        payload = {
            "trace_id": trace_id,
            "kind": kind,
            "wall_time_ns": time.time_ns(),
            "monotonic_ns": time.monotonic_ns(),
            "model": model,
            "inputs": inputs,
            "outputs": outputs,
            "timing": timing,
            "raw": f"raw/{trace_id}.npz" if raw_arrays else None,
            "_raw_arrays": (
                {name: np.asarray(value).copy() for name, value in raw_arrays.items()}
                if raw_arrays
                else None
            ),
        }
        if self._closed:
            raise RuntimeError("trace writer is closed")
        if self._error is not None:
            raise RuntimeError("trace writer failed") from self._error
        if self._asynchronous:
            self._queue.put(payload)
        else:
            self._write_payload(payload)
        return trace_id

    def _write_payload(self, payload: dict[str, Any]) -> None:
        raw_arrays = payload.pop("_raw_arrays")
        if raw_arrays:
            raw_path = self.output / payload["raw"]
            with raw_path.open("xb") as stream:
                np.savez_compressed(stream, **raw_arrays)
        payload["previous_sha256"] = self._previous
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload["record_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
        self._previous = payload["record_sha256"]

    def _worker(self) -> None:
        while True:
            payload = self._queue.get()
            try:
                if payload is None:
                    return
                self._write_payload(payload)
            except BaseException as exc:  # preserve the first writer failure for the caller
                if self._error is None:
                    self._error = exc
            finally:
                self._queue.task_done()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._asynchronous and self._thread is not None:
            self._queue.put(None)
            self._queue.join()
            self._thread.join()
        if self._error is not None:
            raise RuntimeError("trace writer failed") from self._error


class CommandLedger:
    """Reject actuator commands that cannot cite an existing model trace."""

    def __init__(self) -> None:
        self._traces: set[str] = set()
        self.commands: list[dict[str, Any]] = []

    def register(self, trace_id: str) -> None:
        if not trace_id:
            raise ValueError("empty model trace id")
        self._traces.add(trace_id)

    def record_command(
        self,
        trace_id: str,
        command: np.ndarray,
        *,
        safety_limited: bool,
        kind: str,
    ) -> None:
        if trace_id not in self._traces:
            raise RuntimeError(f"command has no registered model trace: {trace_id}")
        self.commands.append(
            {
                "trace_id": trace_id,
                "kind": kind,
                "command": np.asarray(command, dtype=float).tolist(),
                "safety_limited": bool(safety_limited),
            }
        )
