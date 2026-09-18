"""Safe, cross-platform Radeon/ROCm environment probe."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import psutil

from buildguard.config import Settings
from buildguard.monitoring.amd_smi import AmdSmiMonitor
from buildguard.monitoring.rocm_smi import RocmSmiMonitor
from buildguard.system.runtime_info import Availability, GPUInfo, RuntimeInfo


class EnvironmentProbe:
    """Inspect local capabilities; expected failures are returned as data."""

    COMMANDS = ("rocminfo", "amd-smi", "rocm-smi", "llama-server")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _commands(self) -> dict[str, Availability]:
        result: dict[str, Availability] = {}
        for command in self.COMMANDS:
            path = shutil.which(command)
            result[command] = Availability(
                available=path is not None,
                path=path,
                detail=None if path else f"{command} not found on PATH",
            )
        return result

    def _rocm_info(self, executable: str | None) -> tuple[str | None, list[GPUInfo]]:
        if not executable:
            return None, []
        try:
            result = subprocess.run(
                [executable],
                capture_output=True,
                text=True,
                timeout=self.settings.monitoring.command_timeout_seconds,
                check=False,
            )
            text = result.stdout
            names = [
                line.split(":", 1)[1].strip()
                for line in text.splitlines()
                if "Marketing Name:" in line and "CPU" not in line.upper()
            ]
            version = next(
                (
                    line.split(":", 1)[1].strip()
                    for line in text.splitlines()
                    if "Runtime Version:" in line
                ),
                None,
            )
            return version, [GPUInfo(name=name) for name in dict.fromkeys(names) if name]
        except (OSError, subprocess.SubprocessError):
            return None, []

    def _gpu_monitor_info(self) -> list[GPUInfo]:
        for monitor in (
            AmdSmiMonitor(self.settings.monitoring.command_timeout_seconds),
            RocmSmiMonitor(self.settings.monitoring.command_timeout_seconds),
        ):
            snapshot = monitor.snapshot()
            if snapshot.available and snapshot.gpus:
                return [
                    GPUInfo(name=gpu.name or "AMD GPU", memory_total_mb=gpu.memory_total_mb)
                    for gpu in snapshot.gpus
                ]
        return []

    def _endpoint(self) -> Availability:
        if self.settings.llm.mode == "mock":
            return Availability(available=True, detail="deterministic mock mode")
        from buildguard.benchmark import validate_local_endpoint

        try:
            validate_local_endpoint(self.settings.llm, self.settings.permissions)
            url = f"{str(self.settings.llm.endpoint).rstrip('/')}/models"
            response = httpx.get(url, timeout=min(self.settings.llm.timeout_seconds, 5))
            response.raise_for_status()
            return Availability(available=True, detail="local LLM endpoint reachable")
        except Exception as exc:
            return Availability(available=False, detail=str(exc))

    def probe(self) -> RuntimeInfo:
        """Return a complete report even on hosts without ROCm."""
        commands = self._commands()
        rocm_version, rocminfo_gpus = self._rocm_info(commands["rocminfo"].path)
        monitor_gpus = self._gpu_monitor_info()
        gpus = monitor_gpus or rocminfo_gpus
        return RuntimeInfo(
            operating_system=f"{platform.system()} {platform.release()}",
            python_version=sys.version.split()[0],
            cpu_count=psutil.cpu_count(logical=True) or 0,
            memory_total_mb=psutil.virtual_memory().total / (1024 * 1024),
            commands=commands,
            llm_endpoint=self._endpoint(),
            amd_gpu_detected=bool(gpus),
            rocm_version=rocm_version,
            gpus=gpus,
        )

    def write(self, path: Path) -> RuntimeInfo:
        """Probe and save a formatted JSON report."""
        report = self.probe()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
        return report

