"""Stage J — Health Monitor & Metrics Collector.

Collects system-level GPU metrics (VRAM, GPU util via rocm-smi / nvidia-smi),
llama.cpp server metadata (model name, quantization, GPU layers, context),
and application-level latency/throughput measurements.

Designed for AMD Radeon ROCm stack — falls back gracefully on non-ROCm hosts.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("projectpack.monitor")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class GPUMetrics:
    """Snapshot of GPU metrics for a single device."""

    device_id: int = 0
    name: str = ""
    vram_total_mb: float = 0.0
    vram_used_mb: float = 0.0
    vram_free_mb: float = 0.0
    utilization_pct: float = 0.0
    temperature_c: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ModelMetadata:
    """Metadata about the currently loaded llama.cpp model."""

    model_name: str = ""
    model_path: str = ""
    quantization: str = ""
    context_size: int = 0
    gpu_layers: int = 0
    backend: str = "rocm"  # "rocm" | "cuda" | "cpu"
    llama_cpp_version: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class LatencyMetrics:
    """End-to-end and per-stage latency breakdown."""

    first_token_latency_ms: float = 0.0
    generation_tokens_per_second: float = 0.0
    embedding_throughput_texts_per_second: float = 0.0
    end_to_end_latency_ms: float = 0.0
    sample_count: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class SystemMetrics:
    """Host-level system metrics."""

    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_free_gb: float = 0.0
    disk_used_pct: float = 0.0
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


class HealthMonitor:
    """Collects and exposes GPU, model, latency, and system metrics."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._latency = LatencyMetrics()

        # Detection
        self._rocm_smi_path = shutil.which("rocm-smi") or ""
        self._nvidia_smi_path = shutil.which("nvidia-smi") or ""
        self._backend = self._detect_backend()

        # Error tracking
        self._llm_error_count: int = 0
        self._llm_call_count: int = 0
        self._embedding_error_count: int = 0
        self._embedding_call_count: int = 0

        # Cached model metadata
        self._model_metadata: ModelMetadata | None = None

        # Alert state
        self._last_alert_sent: dict[str, float] = {}

    # ------------------------------------------------------------------
    # GPU metrics
    # ------------------------------------------------------------------

    async def collect_gpu_metrics(self) -> list[GPUMetrics]:
        """Collect GPU metrics from available backend.

        Prefers rocm-smi on AMD, falls back to nvidia-smi on CUDA.
        Returns an empty list when no GPU tools are available.
        """
        if self._backend == "rocm" and self._rocm_smi_path:
            return await self._rocm_metrics()
        if self._backend == "cuda" and self._nvidia_smi_path:
            return await self._nvidia_metrics()
        return []

    async def _rocm_metrics(self) -> list[GPUMetrics]:
        """Parse the live ROCm SMI metrics emitted by AMD GPU hosts."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._rocm_smi_path,
                "--showmeminfo",
                "vram",
                "--showuse",
                "--showtemp",
                "--showproductname",
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=15
            )
            if proc.returncode != 0:
                logger.warning("rocm-smi exited %d: %s", proc.returncode, stderr)
                return []

            return self.parse_rocm_smi_json(stdout)
        except asyncio.TimeoutError:
            logger.warning("rocm-smi timed out")
            return []
        except Exception as exc:
            logger.error("Failed to collect ROCm metrics: %s", exc)
            return []

    @staticmethod
    def parse_rocm_smi_json(payload: bytes | str) -> list[GPUMetrics]:
        """Convert ROCm SMI JSON into stable API metrics.

        ROCm SMI has used more than one JSON schema.  Current cloud images
        return direct byte fields such as ``VRAM Total Memory (B)`` while
        older versions nest memory values under ``VRAM`` in MB.  Supporting
        both keeps the dashboard useful across Radeon images.
        """
        import json

        try:
            data = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

        def number(value: object) -> float:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.replace("%", "").strip() or "0")
                except ValueError:
                    return 0.0
            return 0.0

        results: list[GPUMetrics] = []
        for gpu_id, raw_gpu_data in data.items():
            if not isinstance(raw_gpu_data, dict):
                continue
            gpu_data: dict[str, object] = raw_gpu_data
            try:
                device_id = int(str(gpu_id).replace("card", ""))
            except ValueError:
                device_id = len(results)

            legacy_vram = gpu_data.get("VRAM")
            legacy_vram_data = (
                legacy_vram[0]
                if isinstance(legacy_vram, list) and legacy_vram and isinstance(legacy_vram[0], dict)
                else {}
            )
            total_mb = number(gpu_data.get("VRAM Total Memory (B)")) / (1024**2)
            used_mb = number(gpu_data.get("VRAM Total Used Memory (B)")) / (1024**2)
            if total_mb == 0:
                total_mb = number(legacy_vram_data.get("Total Memory (MB)"))
            if used_mb == 0:
                used_mb = number(legacy_vram_data.get("Used Memory (MB)"))

            results.append(
                GPUMetrics(
                    device_id=device_id,
                    name=str(
                        gpu_data.get("Card Series")
                        or gpu_data.get("Device Name")
                        or gpu_data.get("Card Model")
                        or f"AMD GPU {device_id}"
                    ),
                    vram_total_mb=round(total_mb, 1),
                    vram_used_mb=round(used_mb, 1),
                    vram_free_mb=round(max(total_mb - used_mb, 0.0), 1),
                    utilization_pct=number(gpu_data.get("GPU use (%)")),
                    temperature_c=number(gpu_data.get("Temperature (Sensor edge) (C)")),
                )
            )
        return results

    async def _nvidia_metrics(self) -> list[GPUMetrics]:
        """Parse ``nvidia-smi`` output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._nvidia_smi_path,
                "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=15
            )
            if proc.returncode != 0:
                return []

            results: list[GPUMetrics] = []
            for line in stdout.decode().strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 7:
                    results.append(
                        GPUMetrics(
                            device_id=int(parts[0]),
                            name=parts[1],
                            vram_total_mb=float(parts[2]),
                            vram_used_mb=float(parts[3]),
                            vram_free_mb=float(parts[4]),
                            utilization_pct=float(parts[5]),
                            temperature_c=float(parts[6]),
                        )
                    )
            return results
        except Exception as exc:
            logger.error("Failed to collect NVIDIA metrics: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Model metadata (from llama.cpp /v1/models endpoint)
    # ------------------------------------------------------------------

    async def collect_model_metadata(
        self, transport: httpx.AsyncBaseTransport | None = None
    ) -> ModelMetadata:
        """Query the LLM endpoint for model metadata via /v1/models."""
        try:
            async with httpx.AsyncClient(
                transport=transport, timeout=10.0
            ) as client:
                resp = await client.get(
                    f"{str(self._settings.llm_base_url).rstrip('/')}/models"
                )
                resp.raise_for_status()
                data = resp.json()

                models = data.get("data", [])
                if models:
                    m = models[0]
                    model_details = (
                        m.get("meta", {}) if isinstance(m.get("meta"), dict) else {}
                    )
                    meta = ModelMetadata(
                        model_name=m.get("id", ""),
                        model_path="",
                        quantization=self._infer_quantization(m.get("id", "")),
                        context_size=int(model_details.get("n_ctx", 0) or 0),
                        # The OpenAI-compatible endpoint does not expose loaded
                        # GPU layer count; never mislabel agent steps.
                        gpu_layers=0,
                        backend=self._backend,
                        llama_cpp_version="",
                    )
                    self._model_metadata = meta
                    return meta
        except Exception as exc:
            logger.warning("Could not fetch model metadata: %s", exc)

        return self._model_metadata or ModelMetadata()

    @staticmethod
    def _infer_quantization(model_name: str) -> str:
        for fmt in ("IQ2_M", "IQ4_XS", "Q4_K_M", "Q5_K_M", "Q8_0", "F16"):
            if fmt in model_name:
                return fmt
        return "unknown"

    @staticmethod
    def _infer_context(data: dict) -> int:
        # Try to read from model info
        return 0

    # ------------------------------------------------------------------
    # Latency tracking
    # ------------------------------------------------------------------

    def record_llm_latency(
        self,
        first_token_ms: float,
        tokens_per_sec: float,
        total_ms: float,
    ) -> None:
        """Record a single LLM generation latency sample (exponential moving avg)."""
        alpha = 0.1
        self._llm_call_count += 1
        stats = self._latency
        if stats.sample_count == 0:
            stats.first_token_latency_ms = first_token_ms
            stats.generation_tokens_per_second = tokens_per_sec
            stats.end_to_end_latency_ms = total_ms
        else:
            stats.first_token_latency_ms = (
                alpha * first_token_ms
                + (1 - alpha) * stats.first_token_latency_ms
            )
            stats.generation_tokens_per_second = (
                alpha * tokens_per_sec
                + (1 - alpha) * stats.generation_tokens_per_second
            )
            stats.end_to_end_latency_ms = (
                alpha * total_ms + (1 - alpha) * stats.end_to_end_latency_ms
            )
        stats.sample_count += 1
        stats.timestamp = time.time()

    def record_embedding_latency(
        self,
        texts_per_second: float,
        total_ms: float,
        num_texts: int = 1,
    ) -> None:
        """Record embedding throughput."""
        self._embedding_call_count += 1
        alpha = 0.1
        stats = self._latency
        if stats.sample_count == 0:
            stats.embedding_throughput_texts_per_second = texts_per_second
        else:
            stats.embedding_throughput_texts_per_second = (
                alpha * texts_per_second
                + (1 - alpha) * stats.embedding_throughput_texts_per_second
            )
        stats.timestamp = time.time()

    def record_llm_error(self) -> None:
        self._llm_error_count += 1
        self._llm_call_count += 1

    def record_embedding_error(self) -> None:
        self._embedding_error_count += 1
        self._embedding_call_count += 1

    # ------------------------------------------------------------------
    # System metrics (disk)
    # ------------------------------------------------------------------

    async def collect_system_metrics(self) -> SystemMetrics:
        """Collect host-level disk usage for the workspace volume."""
        try:
            root = self._settings.project_root
            usage = shutil.disk_usage(root)
            total_gb = usage.total / (1024**3)
            used_gb = usage.used / (1024**3)
            free_gb = usage.free / (1024**3)
            return SystemMetrics(
                disk_total_gb=round(total_gb, 2),
                disk_used_gb=round(used_gb, 2),
                disk_free_gb=round(free_gb, 2),
                disk_used_pct=round(usage.used / usage.total * 100, 1),
            )
        except Exception as exc:
            logger.error("Failed to collect disk metrics: %s", exc)
            return SystemMetrics()

    # ------------------------------------------------------------------
    # Health assessment
    # ------------------------------------------------------------------

    async def health_check(
        self, transport: httpx.AsyncBaseTransport | None = None
    ) -> dict[str, Any]:
        """Run a full health assessment and return structured status.

        Returns ``status`` one of: ``"healthy"``, ``"degraded"``, ``"critical"``.
        """
        issues: list[dict[str, str]] = []
        status = "healthy"

        # GPU VRAM check
        gpu_metrics = await self.collect_gpu_metrics()
        for gm in gpu_metrics:
            if gm.vram_total_mb > 0:
                vram_pct = gm.vram_used_mb / gm.vram_total_mb * 100
                if vram_pct >= self._settings.health_vram_critical_threshold_pct:
                    status = "critical"
                    issues.append(
                        {
                            "component": f"gpu_{gm.device_id}_vram",
                            "severity": "critical",
                            "message": f"VRAM at {vram_pct:.1f}% (threshold: {self._settings.health_vram_critical_threshold_pct}%)",
                        }
                    )
                elif vram_pct >= self._settings.health_vram_warning_threshold_pct:
                    if status == "healthy":
                        status = "degraded"
                    issues.append(
                        {
                            "component": f"gpu_{gm.device_id}_vram",
                            "severity": "warning",
                            "message": f"VRAM at {vram_pct:.1f}% (threshold: {self._settings.health_vram_warning_threshold_pct}%)",
                        }
                    )

        # Disk check
        sys_metrics = await self.collect_system_metrics()
        if sys_metrics.disk_used_pct >= self._settings.health_disk_critical_threshold_pct:
            if status == "healthy":
                status = "critical"
            issues.append(
                {
                    "component": "disk",
                    "severity": "critical",
                    "message": f"Disk at {sys_metrics.disk_used_pct:.1f}%",
                }
            )
        elif sys_metrics.disk_used_pct >= self._settings.health_disk_warning_threshold_pct:
            if status == "healthy":
                status = "degraded"
            issues.append(
                {
                    "component": "disk",
                    "severity": "warning",
                    "message": f"Disk at {sys_metrics.disk_used_pct:.1f}%",
                }
            )

        # LLM error rate check
        if self._llm_call_count > 10:
            error_rate = self._llm_error_count / self._llm_call_count * 100
            if error_rate >= self._settings.health_max_llm_error_rate_pct:
                if status == "healthy":
                    status = "degraded"
                issues.append(
                    {
                        "component": "llm",
                        "severity": "warning",
                        "message": f"LLM error rate at {error_rate:.1f}%",
                    }
                )

        # Fetch metadata together with the health probe.  Previously metadata
        # was never collected from this path, so a healthy model was rendered
        # as "unavailable" in the operations page.
        await self.collect_model_metadata(transport)

        # LLM endpoint check
        llm_healthy = await self._check_llm_health(transport)
        if not llm_healthy:
            status = "critical"
            issues.append(
                {
                    "component": "llm_endpoint",
                    "severity": "critical",
                    "message": "LLM endpoint not reachable",
                }
            )

        return {
            "status": status,
            "issues": issues,
            "gpu_metrics": [self._gpu_to_dict(gm) for gm in gpu_metrics],
            "system_metrics": self._sys_to_dict(sys_metrics),
            "model_metadata": self._model_to_dict(
                self._model_metadata or ModelMetadata()
            ),
            "latency_metrics": self._latency_to_dict(),
            "timestamp": time.time(),
        }

    async def _check_llm_health(
        self, transport: httpx.AsyncBaseTransport | None
    ) -> bool:
        try:
            url = str(self._settings.llm_base_url).rstrip("/")
            # Use the base host health endpoint
            health_url = url.rsplit("/", 1)[0] + "/health"
            async with httpx.AsyncClient(
                transport=transport, timeout=5.0
            ) as client:
                resp = await client.get(health_url)
                return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Metrics export
    # ------------------------------------------------------------------

    @property
    def latency_metrics(self) -> LatencyMetrics:
        return self._latency

    @property
    def model_metadata(self) -> ModelMetadata | None:
        return self._model_metadata

    @property
    def llm_error_rate(self) -> float:
        if self._llm_call_count == 0:
            return 0.0
        return round(self._llm_error_count / self._llm_call_count * 100, 2)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_backend() -> str:
        if shutil.which("rocm-smi"):
            return "rocm"
        if shutil.which("nvidia-smi"):
            return "cuda"
        return "cpu"

    @staticmethod
    def _gpu_to_dict(gm: GPUMetrics) -> dict[str, Any]:
        return {
            "device_id": gm.device_id,
            "name": gm.name,
            "vram_total_mb": gm.vram_total_mb,
            "vram_used_mb": gm.vram_used_mb,
            "vram_free_mb": gm.vram_free_mb,
            "utilization_pct": gm.utilization_pct,
            "temperature_c": gm.temperature_c,
            "timestamp": gm.timestamp,
        }

    @staticmethod
    def _model_to_dict(mm: ModelMetadata) -> dict[str, Any]:
        return {
            "model_name": mm.model_name,
            "model_path": mm.model_path,
            "quantization": mm.quantization,
            "context_size": mm.context_size,
            "gpu_layers": mm.gpu_layers,
            "backend": mm.backend,
            "llama_cpp_version": mm.llama_cpp_version,
        }

    @staticmethod
    def _sys_to_dict(sm: SystemMetrics) -> dict[str, Any]:
        return {
            "disk_total_gb": sm.disk_total_gb,
            "disk_used_gb": sm.disk_used_gb,
            "disk_free_gb": sm.disk_free_gb,
            "disk_used_pct": sm.disk_used_pct,
        }

    @staticmethod
    def _latency_to_dict() -> dict[str, Any]:
        return {}  # filled by the caller


# Module-level singleton
_monitor_instance: HealthMonitor | None = None


def get_monitor(settings: Settings | None = None) -> HealthMonitor:
    global _monitor_instance
    if _monitor_instance is None:
        if settings is None:
            settings = Settings()
        _monitor_instance = HealthMonitor(settings)
    return _monitor_instance
