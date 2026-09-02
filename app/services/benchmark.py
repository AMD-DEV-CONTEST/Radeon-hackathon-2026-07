"""Stage J — Benchmark Collection & Comparison.

Collects and persists structured benchmark data (first-token latency,
generation speed, embedding throughput, VRAM usage) and provides
before/after comparison to validate optimization impact.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings


@dataclass
class BenchmarkSnapshot:
    """A single benchmark run snapshot."""

    label: str = ""  # e.g. "baseline" | "post-optimization"
    first_token_latency_ms: float = 0.0
    generation_tokens_per_second: float = 0.0
    embedding_throughput_texts_per_second: float = 0.0
    end_to_end_latency_ms: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    gpu_utilization_pct: float = 0.0
    gpu_model: str = ""
    quantization: str = ""
    llama_cpp_version: str = ""
    backend: str = "rocm"
    context_size: int = 0
    gpu_layers: int = 0
    total_tokens_generated: int = 0
    total_texts_embedded: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def vram_usage_pct(self) -> float:
        if self.vram_total_mb <= 0:
            return 0.0
        return round(self.vram_used_mb / self.vram_total_mb * 100, 1)


class BenchmarkCollector:
    """Manages benchmark snapshots and before/after comparison."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._snapshots: list[BenchmarkSnapshot] = []
        self._storage_path = settings.log_root / "benchmarks.json"

    # ------------------------------------------------------------------
    # collection
    # ------------------------------------------------------------------

    def record(
        self,
        label: str,
        *,
        first_token_latency_ms: float = 0.0,
        generation_tokens_per_second: float = 0.0,
        embedding_throughput_texts_per_second: float = 0.0,
        end_to_end_latency_ms: float = 0.0,
        vram_used_mb: float = 0.0,
        vram_total_mb: float = 0.0,
        gpu_utilization_pct: float = 0.0,
        gpu_model: str = "",
        quantization: str = "",
        llama_cpp_version: str = "",
        backend: str = "rocm",
        context_size: int = 0,
        gpu_layers: int = 0,
        total_tokens_generated: int = 0,
        total_texts_embedded: int = 0,
    ) -> BenchmarkSnapshot:
        """Record a new benchmark snapshot."""
        snap = BenchmarkSnapshot(
            label=label,
            first_token_latency_ms=first_token_latency_ms,
            generation_tokens_per_second=generation_tokens_per_second,
            embedding_throughput_texts_per_second=embedding_throughput_texts_per_second,
            end_to_end_latency_ms=end_to_end_latency_ms,
            vram_used_mb=vram_used_mb,
            vram_total_mb=vram_total_mb,
            gpu_utilization_pct=gpu_utilization_pct,
            gpu_model=gpu_model,
            quantization=quantization,
            llama_cpp_version=llama_cpp_version,
            backend=backend,
            context_size=context_size,
            gpu_layers=gpu_layers,
            total_tokens_generated=total_tokens_generated,
            total_texts_embedded=total_texts_embedded,
        )
        self._snapshots.append(snap)
        return snap

    # ------------------------------------------------------------------
    # comparison
    # ------------------------------------------------------------------

    def compare(
        self,
        baseline_label: str = "baseline",
        optimized_label: str = "post-optimization",
    ) -> dict[str, Any]:
        """Compare two benchmark snapshots by label.

        Returns a dict with absolute deltas and percentage improvements.
        """
        baseline = self._find_by_label(baseline_label)
        optimized = self._find_by_label(optimized_label)

        if baseline is None or optimized is None:
            return {
                "error": "Missing snapshots",
                "baseline_found": baseline is not None,
                "optimized_found": optimized is not None,
            }

        return self._compute_comparison(baseline, optimized)

    def compare_latest_two(self) -> dict[str, Any]:
        """Compare the two most recent snapshots."""
        if len(self._snapshots) < 2:
            return {
                "error": "Need at least 2 snapshots",
                "snapshot_count": len(self._snapshots),
            }
        return self._compute_comparison(self._snapshots[-2], self._snapshots[-1])

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def save(self) -> Path:
        """Persist all snapshots to disk as JSON."""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(s) for s in self._snapshots]
        self._storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return self._storage_path

    def load(self) -> list[BenchmarkSnapshot]:
        """Load snapshots from disk."""
        if not self._storage_path.exists():
            return []
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self._snapshots = [
                BenchmarkSnapshot(**item)
                for item in data
            ]
            return list(self._snapshots)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # metrics
    # ------------------------------------------------------------------

    @property
    def latest(self) -> BenchmarkSnapshot | None:
        return self._snapshots[-1] if self._snapshots else None

    @property
    def snapshot_count(self) -> int:
        return len(self._snapshots)

    def list_labels(self) -> list[str]:
        return [s.label for s in self._snapshots]

    def clear(self) -> None:
        self._snapshots.clear()

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _find_by_label(self, label: str) -> BenchmarkSnapshot | None:
        for s in reversed(self._snapshots):
            if s.label == label:
                return s
        return None

    @staticmethod
    def _compute_comparison(
        before: BenchmarkSnapshot,
        after: BenchmarkSnapshot,
    ) -> dict[str, Any]:
        def delta_pct(old: float, new: float) -> float:
            """Improvement percentage: positive = better (lower latency / higher throughput)."""
            if old == 0:
                return 0.0
            # For latency metrics, lower is better → negative delta is improvement
            return round((old - new) / old * 100, 2)

        def delta_pct_higher(old: float, new: float) -> float:
            """Improvement percentage: positive = better (higher throughput)."""
            if old == 0:
                return 0.0
            return round((new - old) / old * 100, 2)

        return {
            "baseline_label": before.label,
            "optimized_label": after.label,
            "first_token_latency": {
                "before_ms": before.first_token_latency_ms,
                "after_ms": after.first_token_latency_ms,
                "improvement_pct": delta_pct(
                    before.first_token_latency_ms, after.first_token_latency_ms
                ),
            },
            "generation_speed": {
                "before_tokens_per_sec": before.generation_tokens_per_second,
                "after_tokens_per_sec": after.generation_tokens_per_second,
                "improvement_pct": delta_pct_higher(
                    before.generation_tokens_per_second,
                    after.generation_tokens_per_second,
                ),
            },
            "embedding_throughput": {
                "before_texts_per_sec": before.embedding_throughput_texts_per_second,
                "after_texts_per_sec": after.embedding_throughput_texts_per_second,
                "improvement_pct": delta_pct_higher(
                    before.embedding_throughput_texts_per_second,
                    after.embedding_throughput_texts_per_second,
                ),
            },
            "end_to_end_latency": {
                "before_ms": before.end_to_end_latency_ms,
                "after_ms": after.end_to_end_latency_ms,
                "improvement_pct": delta_pct(
                    before.end_to_end_latency_ms, after.end_to_end_latency_ms
                ),
            },
            "vram_usage": {
                "before_mb": before.vram_used_mb,
                "after_mb": after.vram_used_mb,
                "improvement_mb": round(before.vram_used_mb - after.vram_used_mb, 1),
                "improvement_pct": delta_pct(
                    before.vram_used_mb, after.vram_used_mb
                ),
            },
            "gpu_utilization": {
                "before_pct": before.gpu_utilization_pct,
                "after_pct": after.gpu_utilization_pct,
            },
            "hardware_info": {
                "gpu_model": before.gpu_model,
                "quantization": before.quantization,
                "llama_cpp_version": before.llama_cpp_version,
                "backend": before.backend,
            },
        }


# Module-level singleton
_benchmark_instance: BenchmarkCollector | None = None


def get_benchmark(settings: Settings | None = None) -> BenchmarkCollector:
    global _benchmark_instance
    if _benchmark_instance is None:
        if settings is None:
            settings = Settings()
        _benchmark_instance = BenchmarkCollector(settings)
    return _benchmark_instance
