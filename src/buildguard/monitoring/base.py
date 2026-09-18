"""Hardware monitor interfaces and orchestration."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from buildguard.utils.serialization import append_jsonl
from buildguard.utils.time import utc_now

LOGGER = logging.getLogger(__name__)


class GPUStats(BaseModel):
    """One GPU's current telemetry."""

    name: str | None = None
    utilization_percent: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    temperature_celsius: float | None = None
    power_watts: float | None = None


class HardwareSnapshot(BaseModel):
    """A point-in-time hardware sample."""

    timestamp: str = Field(default_factory=lambda: utc_now().isoformat())
    source: str
    available: bool = True
    error: str | None = None
    cpu_percent: float | None = None
    process_memory_mb: float | None = None
    system_memory_percent: float | None = None
    gpus: list[GPUStats] = Field(default_factory=list)


class BaseHardwareMonitor(ABC):
    """Sampling contract shared by all monitors."""

    def __init__(self, sample_interval_seconds: float = 1.0) -> None:
        self.sample_interval_seconds = sample_interval_seconds
        self.samples: list[HardwareSnapshot] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @abstractmethod
    def snapshot(self) -> HardwareSnapshot:
        """Capture telemetry without raising for expected tool failures."""

    def _sample_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.samples.append(self.snapshot())
            except Exception as exc:
                LOGGER.exception("Unexpected monitor sampling failure")
                self.samples.append(
                    HardwareSnapshot(source=type(self).__name__, available=False, error=str(exc))
                )
            self._stop_event.wait(self.sample_interval_seconds)

    def start_sampling(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop_sampling(self) -> list[HardwareSnapshot]:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.sample_interval_seconds + 1)
        return list(self.samples)

    def export_jsonl(self, path: Path) -> None:
        for sample in self.samples:
            append_jsonl(path, sample)


class CompositeMonitor(BaseHardwareMonitor):
    """Prefer AMD GPU telemetry while always including process statistics."""

    def __init__(
        self,
        monitors: list[BaseHardwareMonitor],
        sample_interval_seconds: float = 1.0,
    ) -> None:
        super().__init__(sample_interval_seconds)
        self.monitors = monitors

    def snapshot(self) -> HardwareSnapshot:
        snapshots: list[HardwareSnapshot] = []
        for monitor in self.monitors:
            try:
                snapshots.append(monitor.snapshot())
            except Exception as exc:
                LOGGER.warning(
                    "Hardware monitor %s failed without stopping sampling: %s",
                    type(monitor).__name__,
                    exc,
                )
                snapshots.append(
                    HardwareSnapshot(
                        source=type(monitor).__name__,
                        available=False,
                        error=str(exc),
                    )
                )
        process = next((item for item in snapshots if item.source == "process"), None)
        gpu = next((item for item in snapshots if item.available and item.gpus), None)
        return HardwareSnapshot(
            source=f"composite:{gpu.source if gpu else 'process'}",
            available=any(item.available for item in snapshots),
            error=None if gpu else "; ".join(item.error for item in snapshots if item.error) or None,
            cpu_percent=process.cpu_percent if process else None,
            process_memory_mb=process.process_memory_mb if process else None,
            system_memory_percent=process.system_memory_percent if process else None,
            gpus=gpu.gpus if gpu else [],
        )
