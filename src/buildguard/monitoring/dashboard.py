"""Real telemetry aggregation and deterministic export for the local dashboard."""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from buildguard.exceptions import ConfigurationError
from buildguard.monitoring.base import BaseHardwareMonitor, HardwareSnapshot
from buildguard.realtime.camera_manager import CameraManager
from buildguard.scheduling.gpu_scheduler import GpuScheduler
from buildguard.scheduling.runtime_gate import ResourceProvider
from buildguard.schemas.common import StrictSchema
from buildguard.utils.time import utc_now

LOGGER = logging.getLogger(__name__)
ExportFormat = Literal["json", "csv", "chart"]


class DashboardMetricSample(StrictSchema):
    timestamp: datetime = Field(default_factory=utc_now)
    hardware: HardwareSnapshot
    rocm_version: str | None = None
    current_models: list[str] = Field(default_factory=list)
    ttft_seconds: float | None = Field(default=None, ge=0)
    tokens_per_second: float | None = Field(default=None, ge=0)
    llm_total_seconds: float | None = Field(default=None, ge=0)
    rag_latency_ms: float | None = Field(default=None, ge=0)
    reranker_latency_ms: float | None = Field(default=None, ge=0)
    vision_latency_ms: float | None = Field(default=None, ge=0)
    event_confirmation_latency_ms: float | None = Field(default=None, ge=0)
    report_generation_latency_ms: float | None = Field(default=None, ge=0)
    end_to_end_ms: float | None = Field(default=None, ge=0)
    rgc_before_calls: int | None = Field(default=None, ge=0)
    rgc_after_calls: int | None = Field(default=None, ge=0)
    video_fps: dict[str, float] = Field(default_factory=dict)
    queue_lengths: dict[str, int] = Field(default_factory=dict)
    scheduler_queue_length: int = Field(ge=0)


def _latest_duration(
    operations: list[dict[str, Any]],
    keywords: tuple[str, ...],
) -> float | None:
    for item in operations:
        name = str(item.get("operation", "")).casefold()
        if any(keyword in name for keyword in keywords):
            value = item.get("duration_ms")
            if isinstance(value, (int, float)) and value >= 0:
                return float(value)
    return None


def _latest_metric(operations: list[dict[str, Any]], key: str) -> int | None:
    for item in operations:
        metrics = item.get("metrics")
        if isinstance(metrics, dict) and isinstance(metrics.get(key), int):
            return int(metrics[key])
    return None


def _camera_fps(cameras: list[dict[str, object]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in cameras:
        value = item.get("current_fps")
        if isinstance(value, (int, float)):
            result[str(item.get("camera_id", "unknown"))] = float(value)
    return result


def _camera_queue_lengths(cameras: list[dict[str, object]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in cameras:
        camera_id = str(item.get("camera_id", "unknown"))
        inference = item.get("inference_queue")
        if isinstance(inference, dict):
            length = inference.get("length")
            if isinstance(length, int):
                result[f"{camera_id}:inference"] = length
        event_length = item.get("event_queue_length")
        if isinstance(event_length, int):
            result[f"{camera_id}:event"] = event_length
    return result


class PerformanceDashboard:
    """Collect only observed local values; unavailable metrics remain null."""

    def __init__(
        self,
        monitor: BaseHardwareMonitor,
        camera_manager: CameraManager,
        scheduler: GpuScheduler,
        *,
        log_path: Path,
        export_dir: Path,
        workspace_root: Path,
        history_size: int,
        rocm_version: str | None = None,
        resource_provider: ResourceProvider | None = None,
    ) -> None:
        self.monitor = monitor
        self.camera_manager = camera_manager
        self.scheduler = scheduler
        self.workspace_root = workspace_root.resolve()
        self.log_path = log_path.resolve()
        self.export_dir = export_dir.resolve()
        for path, label in (
            (self.log_path, "dashboard_log_path"),
            (self.export_dir, "export_dir"),
        ):
            try:
                path.relative_to(self.workspace_root)
            except ValueError as exc:
                raise ConfigurationError(
                    f"Monitoring {label} must remain inside workspace"
                ) from exc
        self.history: deque[DashboardMetricSample] = deque(maxlen=history_size)
        self.rocm_version = rocm_version
        self.resource_provider = resource_provider
        self._lock = threading.RLock()
        self._load_existing()

    def _load_existing(self) -> None:
        if not self.log_path.is_file():
            return
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            LOGGER.warning("Cannot read dashboard history: %s", exc)
            return
        history_limit = self.history.maxlen or len(lines)
        for line in lines[-history_limit:]:
            try:
                self.history.append(DashboardMetricSample.model_validate_json(line))
            except Exception as exc:
                LOGGER.warning("Skipping damaged dashboard metric line: %s", exc)

    def _append(self, sample: DashboardMetricSample) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(sample.model_dump_json() + "\n")

    def _camera_metrics(self) -> list[dict[str, object]]:
        try:
            return self.camera_manager.runtime_metrics()
        except Exception as exc:
            LOGGER.warning(
                "Camera metrics failed without stopping dashboard collection: %s",
                exc,
            )
            return []

    def collect(
        self,
        *,
        llm_metrics: list[dict[str, Any]],
        operations: list[dict[str, Any]],
    ) -> DashboardMetricSample:
        try:
            hardware = self.monitor.snapshot()
        except Exception as exc:
            LOGGER.warning(
                "Hardware snapshot failed without stopping dashboard collection: %s",
                exc,
            )
            hardware = HardwareSnapshot(
                source=type(self.monitor).__name__,
                available=False,
                error=str(exc),
            )
        cameras = self._camera_metrics()
        latest_llm = llm_metrics[-1] if llm_metrics else {}
        resource = self.scheduler.last_resource
        if self.resource_provider is not None:
            try:
                resource = self.resource_provider() or resource
            except Exception as exc:
                LOGGER.warning("GPU resource snapshot unavailable: %s", exc)
        sample = DashboardMetricSample(
            hardware=hardware,
            rocm_version=self.rocm_version,
            current_models=(
                sorted(resource.resident_models)
                if resource is not None
                else []
            ),
            ttft_seconds=(
                float(latest_llm["ttft_seconds"])
                if isinstance(latest_llm.get("ttft_seconds"), (int, float))
                else None
            ),
            tokens_per_second=(
                float(latest_llm["tokens_per_second"])
                if isinstance(latest_llm.get("tokens_per_second"), (int, float))
                else None
            ),
            llm_total_seconds=(
                float(latest_llm["total_seconds"])
                if isinstance(latest_llm.get("total_seconds"), (int, float))
                else None
            ),
            rag_latency_ms=_latest_duration(operations, ("rag", "retrieval")),
            reranker_latency_ms=_latest_duration(operations, ("rerank",)),
            vision_latency_ms=_latest_duration(operations, ("vision", "inspection")),
            event_confirmation_latency_ms=_latest_duration(
                operations,
                ("event_confirmation",),
            ),
            report_generation_latency_ms=_latest_duration(
                operations,
                ("report_generation", "report_export"),
            ),
            end_to_end_ms=_latest_duration(
                operations,
                ("end_to_end", "mvp_inspection"),
            ),
            rgc_before_calls=_latest_metric(operations, "rgc_before_calls"),
            rgc_after_calls=_latest_metric(operations, "rgc_after_calls"),
            video_fps=_camera_fps(cameras),
            queue_lengths=_camera_queue_lengths(cameras),
            scheduler_queue_length=self.scheduler.queue_length,
        )
        with self._lock:
            self.history.append(sample)
            try:
                self._append(sample)
            except OSError as exc:
                LOGGER.warning("Dashboard metric append failed: %s", exc)
        return sample

    def payload(
        self,
        *,
        llm_metrics: list[dict[str, Any]],
        operations: list[dict[str, Any]],
        limit: int,
    ) -> dict[str, Any]:
        self.collect(llm_metrics=llm_metrics, operations=operations)
        with self._lock:
            samples = list(self.history)[-limit:]
        rgc = [
            item
            for item in operations
            if isinstance(item.get("metrics"), dict)
            and (
                "rgc_before_calls" in item["metrics"]
                or "rgc_after_calls" in item["metrics"]
            )
        ]
        quantization = [
            item
            for item in operations
            if isinstance(item.get("metrics"), dict)
            and "quantization" in item["metrics"]
        ]
        return {
            "samples": [item.model_dump(mode="json") for item in samples],
            "cameras": self._camera_metrics(),
            "tool_timeline": operations,
            "task_waterfall": operations,
            "rgc_comparison": rgc,
            "quantization_comparison": quantization,
            "data_sources": {
                "hardware": "amd-smi/rocm-smi/nvidia-smi with process fallback",
                "operations": "SQLite performance_logs",
                "llm": "local backend token metrics",
                "cameras": "CameraManager runtime state",
            },
        }

    def export(
        self,
        payload: dict[str, Any],
        export_format: ExportFormat,
    ) -> tuple[bytes, str, str]:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        if export_format == "json":
            content = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=str,
            ).encode()
            suffix, media = "json", "application/json"
        elif export_format == "chart":
            chart = [
                {
                    "timestamp": item["timestamp"],
                    "gpu_utilization_percent": (
                        item["hardware"]["gpus"][0].get("utilization_percent")
                        if item["hardware"].get("gpus")
                        else None
                    ),
                    "vram_used_mb": (
                        item["hardware"]["gpus"][0].get("memory_used_mb")
                        if item["hardware"].get("gpus")
                        else None
                    ),
                    "video_fps": item["video_fps"],
                    "queue_lengths": item["queue_lengths"],
                }
                for item in payload.get("samples", [])
            ]
            content = json.dumps(
                {"chart_series": chart},
                ensure_ascii=False,
                indent=2,
            ).encode()
            suffix, media = "chart.json", "application/json"
        else:
            stream = io.StringIO()
            fields = [
                "timestamp",
                "gpu_name",
                "gpu_utilization_percent",
                "vram_used_mb",
                "vram_total_mb",
                "temperature_celsius",
                "power_watts",
                "ttft_seconds",
                "tokens_per_second",
                "vision_latency_ms",
                "end_to_end_ms",
                "scheduler_queue_length",
            ]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for item in payload.get("samples", []):
                gpus = item["hardware"].get("gpus", [])
                gpu = gpus[0] if gpus else {}
                writer.writerow(
                    {
                        "timestamp": item["timestamp"],
                        "gpu_name": gpu.get("name"),
                        "gpu_utilization_percent": gpu.get("utilization_percent"),
                        "vram_used_mb": gpu.get("memory_used_mb"),
                        "vram_total_mb": gpu.get("memory_total_mb"),
                        "temperature_celsius": gpu.get("temperature_celsius"),
                        "power_watts": gpu.get("power_watts"),
                        "ttft_seconds": item.get("ttft_seconds"),
                        "tokens_per_second": item.get("tokens_per_second"),
                        "vision_latency_ms": item.get("vision_latency_ms"),
                        "end_to_end_ms": item.get("end_to_end_ms"),
                        "scheduler_queue_length": item.get(
                            "scheduler_queue_length"
                        ),
                    }
                )
            content = stream.getvalue().encode("utf-8-sig")
            suffix, media = "csv", "text/csv"
        filename = f"buildguard-performance-{timestamp}.{suffix}"
        target = self.export_dir / filename
        target.write_bytes(content)
        return content, media, filename
