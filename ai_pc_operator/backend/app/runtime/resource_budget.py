"""RAM-aware startup and model loading budget."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class MemorySnapshot:
    total_mb: int
    available_mb: int
    percent_used: float


@dataclass(frozen=True)
class RuntimeBudget:
    available_mb: int
    model_budget_mb: int
    allow_ocr: bool
    allow_detector: bool
    allow_llm: bool
    mode: str


class ResourceBudget:
    """Measures memory and decides which tiers are allowed."""

    def __init__(
        self,
        reserve_mb: int = 900,
        max_model_budget_mb: int = 1400,
    ) -> None:
        self.reserve_mb = reserve_mb
        self.max_model_budget_mb = max_model_budget_mb
        self.current = self.measure()

    def measure(self) -> RuntimeBudget:
        snapshot = self.snapshot()
        model_budget = max(0, min(self.max_model_budget_mb, snapshot.available_mb - self.reserve_mb))
        budget = RuntimeBudget(
            available_mb=snapshot.available_mb,
            model_budget_mb=model_budget,
            allow_ocr=model_budget >= 160,
            allow_detector=model_budget >= 350,
            allow_llm=model_budget >= 1200,
            mode=self._mode(model_budget),
        )
        self.current = budget
        return budget

    def snapshot(self) -> MemorySnapshot:
        override = os.environ.get("SCREEN_AI_RAM_MB")
        if override:
            try:
                available = max(0, int(override))
                return MemorySnapshot(
                    total_mb=max(available, 4096),
                    available_mb=available,
                    percent_used=0.0,
                )
            except ValueError:
                pass

        try:
            import psutil

            vm = psutil.virtual_memory()
            return MemorySnapshot(
                total_mb=int(vm.total / (1024**2)),
                available_mb=int(vm.available / (1024**2)),
                percent_used=float(vm.percent),
            )
        except Exception:
            # Conservative fallback for environments without psutil.
            return MemorySnapshot(total_mb=4096, available_mb=1024, percent_used=75.0)

    def can_load(self, estimated_mb: int) -> bool:
        budget = self.measure()
        return estimated_mb <= budget.model_budget_mb

    def _mode(self, model_budget: int) -> str:
        if model_budget >= 1200:
            return "balanced"
        if model_budget >= 350:
            return "perception-only"
        if model_budget >= 160:
            return "ocr-only"
        return "tier0-only"
