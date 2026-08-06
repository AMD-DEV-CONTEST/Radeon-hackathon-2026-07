"""CPU and process memory monitor."""

import os

import psutil

from buildguard.monitoring.base import BaseHardwareMonitor, HardwareSnapshot


class ProcessMonitor(BaseHardwareMonitor):
    """Collect telemetry available on every supported platform."""

    def snapshot(self) -> HardwareSnapshot:
        process = psutil.Process(os.getpid())
        return HardwareSnapshot(
            source="process",
            cpu_percent=psutil.cpu_percent(interval=None),
            process_memory_mb=process.memory_info().rss / (1024 * 1024),
            system_memory_percent=psutil.virtual_memory().percent,
        )

