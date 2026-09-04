"""Best-effort AMD SMI sampler used only around measured requests."""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Any


PATTERNS = {
    "gpu_utilization_pct": re.compile(r"^\s*GFX_ACTIVITY:\s+(\d+)\s+%", re.M),
    "vram_used_mb": re.compile(r"^\s*USED_VRAM:\s+(\d+)\s+MB", re.M),
    "socket_power_w": re.compile(r"^\s*SOCKET_POWER:\s+(\d+)\s+W", re.M),
    "edge_temperature_c": re.compile(r"^\s*EDGE:\s+(\d+)\s+°C", re.M),
    "hotspot_temperature_c": re.compile(r"^\s*HOTSPOT:\s+(\d+)\s+°C", re.M),
    "vram_temperature_c": re.compile(r"^\s*MEM:\s+(\d+)\s+°C", re.M),
}


@dataclass
class AmdGpuSampler:
    interval_seconds: float = 0.25
    samples: list[dict[str, float | int]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    def __enter__(self) -> "AmdGpuSampler":
        if shutil.which("amd-smi") is None:
            self.errors.append("amd-smi unavailable")
            return self
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _sample_loop(self) -> None:
        while not self._stop.is_set():
            try:
                completed = subprocess.run(
                    ["amd-smi", "metric", "--gpu", "0"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if completed.returncode != 0:
                    self.errors.append(completed.stderr.strip()[:300])
                    return
                sample: dict[str, float | int] = {
                    "timestamp_unix": time.time(),
                }
                for name, pattern in PATTERNS.items():
                    match = pattern.search(completed.stdout)
                    if match:
                        sample[name] = int(match.group(1))
                if len(sample) > 1:
                    self.samples.append(sample)
            except Exception as exc:  # noqa: BLE001 - sampler must not abort run
                self.errors.append(repr(exc))
                return
            self._stop.wait(self.interval_seconds)

    def summary(self) -> dict[str, Any]:
        metrics: dict[str, dict[str, float | int | None]] = {}
        for name in PATTERNS:
            values = [sample[name] for sample in self.samples if name in sample]
            metrics[name] = {
                "count": len(values),
                "mean": mean(values) if values else None,
                "peak": max(values) if values else None,
            }
        return {
            "available": bool(self.samples),
            "sample_count": len(self.samples),
            "metrics": metrics,
            "errors": self.errors,
        }
