"""Honest ROCm/local-LLM benchmark for the currently configured runtime."""

from __future__ import annotations

from typing import Literal

from buildguard.config import EvaluationConfig, Settings
from buildguard.llm.base import ChatMessage, LocalLLMBackend
from buildguard.llm.token_metrics import TokenMetrics
from buildguard.monitoring.amd_smi import AmdSmiMonitor
from buildguard.monitoring.base import CompositeMonitor, HardwareSnapshot
from buildguard.monitoring.process_monitor import ProcessMonitor
from buildguard.monitoring.rocm_smi import RocmSmiMonitor
from buildguard.schemas.common import StrictSchema

ThinkingMode = Literal["non-thinking", "thinking", "dynamic"]


class RocmBenchmarkRecord(StrictSchema):
    thinking_mode: ThinkingMode
    status: Literal["completed", "mock_validation", "unavailable", "failed"]
    quantization: str
    prefix_cache_enabled: bool | None
    context_compression_enabled: bool | None
    model_residency: Literal["unreported", "resident", "on_demand"]
    rgc_enabled: bool | None
    metrics: TokenMetrics | None = None
    start_snapshot: HardwareSnapshot | None = None
    end_snapshot: HardwareSnapshot | None = None
    reason: str | None = None


def _monitor(settings: Settings) -> CompositeMonitor:
    return CompositeMonitor(
        [
            AmdSmiMonitor(settings.monitoring.command_timeout_seconds),
            RocmSmiMonitor(settings.monitoring.command_timeout_seconds),
            ProcessMonitor(settings.monitoring.sample_interval_seconds),
        ],
        settings.monitoring.sample_interval_seconds,
    )


class RocmBenchmarkRunner:
    """Measure one active server configuration without claiming to reconfigure it."""

    def __init__(
        self,
        settings: Settings,
        backend: LocalLLMBackend,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.monitor = _monitor(settings)

    def _unavailable(
        self,
        mode: ThinkingMode,
        reason: str,
    ) -> RocmBenchmarkRecord:
        config = self.settings.evaluation
        return RocmBenchmarkRecord(
            thinking_mode=mode,
            status="unavailable",
            quantization=config.active_quantization,
            prefix_cache_enabled=config.prefix_cache_enabled,
            context_compression_enabled=config.context_compression_enabled,
            model_residency=config.model_residency,
            rgc_enabled=config.rgc_enabled,
            reason=reason,
        )

    def run_mode(self, mode: ThinkingMode) -> RocmBenchmarkRecord:
        if self.settings.llm.mode != "mock" and not self.backend.health_check():
            return self._unavailable(mode, "Configured local LLM service is unavailable")
        start = self.monitor.snapshot()
        prompt = (
            "Inspect a multi-step construction safety task and return a short summary."
            if mode == "dynamic"
            else "Return a short BuildGuard local benchmark response."
        )
        thinking = mode == "thinking" or (
            mode == "dynamic" and "multi-step" in prompt
        )
        try:
            list(
                self.backend.stream_chat(
                    [ChatMessage(role="user", content=prompt)],
                    thinking=thinking,
                )
            )
            history = getattr(self.backend, "metrics_history", [])
            metrics = history[-1] if history else None
            end = self.monitor.snapshot()
            config: EvaluationConfig = self.settings.evaluation
            missing_labels = [
                label
                for label, missing in (
                    (
                        "active_quantization",
                        config.active_quantization == "unreported",
                    ),
                    (
                        "prefix_cache_enabled",
                        config.prefix_cache_enabled is None,
                    ),
                    (
                        "context_compression_enabled",
                        config.context_compression_enabled is None,
                    ),
                    (
                        "model_residency",
                        config.model_residency == "unreported",
                    ),
                    ("rgc_enabled", config.rgc_enabled is None),
                )
                if missing
            ]
            reason: str | None = None
            status: Literal[
                "completed", "mock_validation", "unavailable", "failed"
            ]
            if self.settings.llm.mode == "mock":
                status = "mock_validation"
                reason = "Deterministic mock timing is not a ROCm performance result"
            elif not start.gpus and not end.gpus:
                status = "unavailable"
                reason = "No Radeon GPU telemetry was observed during the benchmark"
            elif missing_labels:
                status = "unavailable"
                reason = (
                    "Benchmark configuration labels are unreported: "
                    + ", ".join(missing_labels)
                )
            else:
                status = "completed"
            return RocmBenchmarkRecord(
                thinking_mode=mode,
                status=status,
                quantization=config.active_quantization,
                prefix_cache_enabled=config.prefix_cache_enabled,
                context_compression_enabled=config.context_compression_enabled,
                model_residency=config.model_residency,
                rgc_enabled=config.rgc_enabled,
                metrics=metrics,
                start_snapshot=start,
                end_snapshot=end,
                reason=reason,
            )
        except Exception as exc:
            return self._unavailable(mode, str(exc)).model_copy(
                update={"status": "failed"}
            )

    def run_matrix(self) -> list[RocmBenchmarkRecord]:
        return [
            self.run_mode(mode)
            for mode in ("non-thinking", "thinking", "dynamic")
        ]
