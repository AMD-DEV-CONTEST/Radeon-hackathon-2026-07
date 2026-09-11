"""ROCm telemetry sampling and package-energy integration."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import subprocess
import threading
import time
from typing import Any, Callable, Mapping


ROCM_SMI_COMMAND = (
    "rocm-smi",
    "--showpower",
    "--showuse",
    "--showmemuse",
    "--json",
)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_rocm_smi(payload: Mapping[str, Any]) -> dict[str, dict[str, float | None]]:
    parsed = {}
    for gpu_id, values in payload.items():
        if not isinstance(values, Mapping):
            continue
        parsed[str(gpu_id)] = {
            "power_w": _number(values.get("Average Graphics Package Power (W)")),
            "gpu_use_percent": _number(values.get("GPU use (%)")),
            "vram_allocated_percent": _number(
                values.get("GPU Memory Allocated (VRAM%)")
            ),
            "memory_activity_percent": _number(
                values.get("GPU Memory Read/Write Activity (%)")
            ),
        }
    if not parsed:
        raise ValueError("rocm-smi returned no GPU records")
    return parsed


def sample_rocm_smi(
    command: tuple[str, ...] = ROCM_SMI_COMMAND,
) -> dict[str, dict[str, float | None]]:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return parse_rocm_smi(json.loads(completed.stdout))


def summarize_rocm_samples(
    samples: list[Mapping[str, Any]], *, gpu_id: str = "card0"
) -> dict[str, Any]:
    valid = []
    for sample in samples:
        timestamp = _number(sample.get("monotonic_seconds"))
        gpu = (sample.get("gpus") or {}).get(gpu_id) or {}
        power = _number(gpu.get("power_w"))
        if timestamp is not None and power is not None:
            valid.append((timestamp, power, gpu))
    valid.sort(key=lambda item: item[0])
    if len(valid) < 2:
        raise ValueError("at least two timestamped ROCm power samples are required")
    if any(right[0] <= left[0] for left, right in zip(valid, valid[1:])):
        raise ValueError("ROCm sample timestamps must be strictly increasing")

    energy_watt_seconds = 0.0
    intervals = []
    for left, right in zip(valid, valid[1:]):
        duration = right[0] - left[0]
        intervals.append(duration)
        energy_watt_seconds += 0.5 * (left[1] + right[1]) * duration
    duration_seconds = valid[-1][0] - valid[0][0]

    def values(name: str) -> list[float]:
        return [
            value
            for _, _, gpu in valid
            if (value := _number(gpu.get(name))) is not None
        ]

    gpu_use = values("gpu_use_percent")
    vram = values("vram_allocated_percent")
    window = max(1, len(vram) // 10) if vram else 0
    vram_growth = (
        statistics.fmean(vram[-window:]) - statistics.fmean(vram[:window])
        if vram
        else None
    )
    sorted_intervals = sorted(intervals)
    p95_index = max(0, math.ceil(0.95 * len(sorted_intervals)) - 1)
    return {
        "schema_version": 1,
        "protocol": "rocm-package-energy-summary-v1",
        "gpu_id": gpu_id,
        "sample_count": len(valid),
        "duration_seconds": duration_seconds,
        "energy_wh": energy_watt_seconds / 3600.0,
        "mean_package_power_w": energy_watt_seconds / duration_seconds,
        "mean_gpu_use_percent": statistics.fmean(gpu_use) if gpu_use else None,
        "peak_vram_allocated_percent": max(vram) if vram else None,
        "vram_growth_percentage_points": vram_growth,
        "p95_sample_interval_seconds": sorted_intervals[p95_index],
        "raw_package_energy_includes_non_policy_gpu_work": True,
    }


class RocmTelemetryRecorder(AbstractContextManager["RocmTelemetryRecorder"]):
    """Sample one Radeon in a background thread while a campaign runs."""

    def __init__(
        self,
        output: Path,
        *,
        interval_seconds: float = 1.0,
        gpu_id: str = "card0",
        sampler: Callable[[], dict[str, dict[str, float | None]]] = sample_rocm_smi,
    ) -> None:
        if interval_seconds <= 0.0:
            raise ValueError("telemetry interval must be positive")
        self.output = output
        self.interval_seconds = interval_seconds
        self.gpu_id = gpu_id
        self.sampler = sampler
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample_once(self) -> None:
        try:
            gpus = self.sampler()
            self.samples.append(
                {
                    "monotonic_seconds": time.monotonic(),
                    "wall_time_utc": datetime.now(timezone.utc).isoformat(),
                    "gpus": gpus,
                }
            )
        except Exception as exc:  # telemetry must not terminate robot safety control
            self.errors.append(f"{type(exc).__name__}:{exc}")

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self._sample_once()
            remaining = max(0.0, self.interval_seconds - (time.monotonic() - started))
            self._stop.wait(remaining)

    def start(self) -> "RocmTelemetryRecorder":
        if self._thread is not None:
            raise RuntimeError("telemetry recorder is already running")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=max(10.0, 2.0 * self.interval_seconds))
        self._sample_once()
        with self.output.open("w", encoding="utf-8") as stream:
            for sample in self.samples:
                stream.write(json.dumps(sample, sort_keys=True) + "\n")
        self._thread = None

    def summary(self) -> dict[str, Any]:
        result = summarize_rocm_samples(self.samples, gpu_id=self.gpu_id)
        result["sampling_error_count"] = len(self.errors)
        result["sampling_errors"] = self.errors[:10]
        result["raw_jsonl"] = str(self.output.resolve())
        return result

    def __enter__(self) -> "RocmTelemetryRecorder":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()
