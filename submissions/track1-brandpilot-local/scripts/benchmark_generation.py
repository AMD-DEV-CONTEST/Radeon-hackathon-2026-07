"""Metadata contract for future real generation benchmarks.

This module deliberately contains no generator and never fabricates timings.
The future ROCm integration should create a ``GenerationBenchmark`` from actual
inputs and measured values, then call ``write_report`` after a real output exists.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GenerationBenchmark:
    model: str
    model_revision: str | None
    prompt: str
    input_image: str
    output_image: str
    width: int
    height: int
    steps: int
    guidance_scale: float
    seed: int
    warm_up_seconds: float
    generation_latency_seconds: float
    peak_gpu_memory_bytes: int | None
    timestamp: str
    device: str
    pytorch_version: str | None
    rocm_version: str | None

    @classmethod
    def from_real_measurement(cls, **values: Any) -> "GenerationBenchmark":
        values.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        benchmark = cls(**values)
        if benchmark.warm_up_seconds < 0 or benchmark.generation_latency_seconds < 0:
            raise ValueError("Measured durations cannot be negative")
        if benchmark.width <= 0 or benchmark.height <= 0 or benchmark.steps <= 0:
            raise ValueError("Dimensions and steps must be positive")
        source = Path(benchmark.input_image)
        if not source.is_file():
            raise FileNotFoundError(f"Input image does not exist: {source}")
        output = Path(benchmark.output_image)
        if not output.is_file():
            raise FileNotFoundError(f"Real output image does not exist: {output}")
        return benchmark


def write_report(benchmark: GenerationBenchmark, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(benchmark), indent=2) + "\n", encoding="utf-8")


def schema() -> dict[str, str]:
    return {
        "model": "Exact model repository or local path",
        "model_revision": "Pinned revision or commit",
        "prompt": "Exact generation prompt",
        "input_image": "Input path and preferably a separate checksum",
        "output_image": "Existing real output path",
        "width / height": "Generated pixel dimensions",
        "steps / guidance_scale / seed": "Generation controls",
        "warm_up_seconds": "Measured model-load or warm-up duration",
        "generation_latency_seconds": "Measured generation-only duration",
        "peak_gpu_memory_bytes": "Measured peak, null only when API unavailable",
        "timestamp": "UTC ISO-8601 timestamp",
        "device": "Recorded device name",
        "pytorch_version / rocm_version": "Recorded runtime versions",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Describe the metadata contract for future real generation benchmarks; does not generate images."
    )
    parser.add_argument("--describe", action="store_true", help="Print the benchmark JSON field descriptions.")
    args = parser.parse_args()
    if not args.describe:
        parser.error("no generation backend is wired; use --describe")
    print(json.dumps(schema(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
