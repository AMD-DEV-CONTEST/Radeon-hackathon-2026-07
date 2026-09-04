#!/usr/bin/env python3
"""Reproducible application benchmark for scalar and PyTorch transport paths."""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from nuclear_agent.gpu_analysis import batched_transport_torch
from nuclear_agent.transport import TransportParameters, simulate_transport


def positive_int(value: str) -> int:
    converted = int(value)
    if converted <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return converted


def inputs(size: int) -> tuple[list[float], list[float]]:
    distances = [10.0 + 190.0 * (index % 257) / 256.0 for index in range(size)]
    times = [1.0e7 + 1.2e10 * (index % 509) / 508.0 for index in range(size)]
    return distances, times


def scalar_reference(params: TransportParameters, distances: list[float], times: list[float]):
    return [
        simulate_transport(params, distance, time_s)["concentration_bq_m3"]
        for distance, time_s in zip(distances, times, strict=True)
    ]


def timed(callable_, repeats: int) -> tuple[object, list[float]]:
    result = None
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = callable_()
        samples.append(time.perf_counter() - start)
    return result, samples


def errors(reference: list[float], candidate: list[float]) -> dict[str, float]:
    absolute = [abs(left - right) for left, right in zip(reference, candidate, strict=True)]
    relative = [
        difference / max(abs(left), 1.0e-30)
        for left, difference in zip(reference, absolute, strict=True)
    ]
    return {"max_abs": max(absolute, default=0.0), "max_rel": max(relative, default=0.0)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=positive_int, nargs="+", default=[1, 128, 4096, 65536])
    parser.add_argument("--repeats", type=positive_int, default=3)
    args = parser.parse_args()

    import torch

    params = TransportParameters(
        initial_concentration_bq_m3=1.0e6,
        distribution_coefficient_m3_kg=0.2,
        bulk_density_kg_m3=1700.0,
        porosity=0.35,
        groundwater_velocity_m_s=1.0e-5,
        dispersion_m2_s=1.0e-3,
        potassium_mg_l=20.0,
        competition_coefficient_l_mg=0.01,
        half_life_years=30.018,
    )
    records = []
    for size in args.sizes:
        distances, times = inputs(size)
        reference, scalar_times = timed(
            lambda: scalar_reference(params, distances, times), args.repeats
        )
        assert isinstance(reference, list)
        for device, dtype in (("cpu", "float64"), ("cuda", "float64"), ("cuda", "float32")):
            if device == "cuda" and not torch.cuda.is_available():
                continue
            # Warm-up is excluded from measured samples.
            batched_transport_torch(params, distances, times, device=device, dtype=dtype)
            result, samples = timed(
                lambda d=device, t=dtype: batched_transport_torch(
                    params, distances, times, device=d, dtype=t
                ),
                args.repeats,
            )
            assert isinstance(result, dict)
            median_s = statistics.median(samples)
            records.append({
                "batch_size": size,
                "backend": f"torch-{device}-{dtype}",
                "median_s": median_s,
                "min_s": min(samples),
                "evaluations_per_s": size / median_s,
                "error_vs_scalar": errors(reference, result["concentration_bq_m3"]),
                "timing_scope": "end-to-end including tensor creation and device-to-host list conversion",
            })
        scalar_median = statistics.median(scalar_times)
        records.append({
            "batch_size": size,
            "backend": "python-scalar-float64",
            "median_s": scalar_median,
            "min_s": min(scalar_times),
            "evaluations_per_s": size / scalar_median,
            "error_vs_scalar": {"max_abs": 0.0, "max_rel": 0.0},
            "timing_scope": "end-to-end scalar canonical reference",
        })

    payload = {
        "benchmark_version": "transport-benchmark-0.1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "gpu_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "repeats": args.repeats,
        "scenario_classification": "demonstration benchmark; parameters declared in script",
        "acceptance": {
            "fp64_max_relative_error": 1.0e-12,
            "fp32_reporting_threshold_max_relative_error": 1.0e-4,
        },
        "records": records,
    }
    fp64_records = [record for record in records if record["backend"].endswith("float64")]
    if any(record["error_vs_scalar"]["max_rel"] > 1.0e-12 for record in fp64_records):
        raise RuntimeError("FP64 parity tolerance exceeded")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
