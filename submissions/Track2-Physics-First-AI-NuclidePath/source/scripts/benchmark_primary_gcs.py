#!/usr/bin/env python3
"""Benchmark exact scalar vs batched primary GCS evaluation."""
import argparse
import gc
import json
import platform
import random
import statistics
import time
from pathlib import Path

from nuclear_agent.gcs import PrimaryGCSState, calculate_primary_kd, load_primary_gcs_parameters
from nuclear_agent.gcs_primary_accelerated import torch
from nuclear_agent.gpu_analysis import batched_primary_gcs_torch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=100000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--dtype", choices=("float32", "float64"), default="float64")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.size < 1 or args.repeats < 1:
        parser.error("size and repeats must be positive")
    if torch is None:
        parser.error("PyTorch is required")

    root = Path(__file__).parents[1]
    params = load_primary_gcs_parameters(root / "src/nuclear_agent/data/parameters/bradbury_baeyens_gcs_v2.json")
    rng = random.Random(args.seed)
    states = tuple(PrimaryGCSState(
        10 ** rng.uniform(-12, -3), 10 ** rng.uniform(-6, -1),
        10 ** rng.uniform(-5, 0), 10 ** rng.uniform(-8, -1),
        rng.uniform(.01, 1), rng.uniform(6, 9),
    ) for _ in range(args.size))

    scalar_times = []
    scalar = None
    for _ in range(args.repeats):
        gc.collect()
        start = time.perf_counter()
        scalar = tuple(calculate_primary_kd(params, s).bulk_kd_l_kg for s in states)
        scalar_times.append(time.perf_counter() - start)

    # Warm-up before measured device runs.
    batched_primary_gcs_torch(params, states, device=args.device, dtype=args.dtype)
    batch_times = []
    accelerated = None
    for _ in range(args.repeats):
        gc.collect()
        start = time.perf_counter()
        accelerated = batched_primary_gcs_torch(params, states, device=args.device, dtype=args.dtype)
        if args.device == "cuda": torch.cuda.synchronize()
        batch_times.append(time.perf_counter() - start)

    errors = [abs(a / b - 1) for a, b in zip(accelerated.bulk_kd_l_kg, scalar)]
    scalar_median = statistics.median(scalar_times)
    batch_median = statistics.median(batch_times)
    props = torch.cuda.get_device_properties(0) if args.device == "cuda" else None
    result = {
        "backend": "torch-exact",
        "approximation": False,
        "size": args.size,
        "repeats": args.repeats,
        "seed": args.seed,
        "device": args.device,
        "dtype": args.dtype,
        "torch": torch.__version__,
        "hip": getattr(torch.version, "hip", None),
        "device_name": torch.cuda.get_device_name(0) if props else (platform.processor() or platform.machine()),
        "scope": "end-to-end Kd APIs including tensor construction and host result conversion; scalar path also constructs rich provenance result objects",
        "scalar_seconds": scalar_times,
        "batched_seconds": batch_times,
        "scalar_median_seconds": scalar_median,
        "batched_median_seconds": batch_median,
        "speedup": scalar_median / batch_median,
        "max_relative_error": max(errors),
        "median_relative_error": statistics.median(errors),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
