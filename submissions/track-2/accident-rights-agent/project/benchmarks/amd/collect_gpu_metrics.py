#!/usr/bin/env python3
"""Collect timestamped AMD GPU utilization, VRAM, power, and temperature."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.amd.common import write_gpu_csv  # noqa: E402
from experiments.memory.gpu import AmdGpuSampler  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--label", default="gpu-monitor")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with AmdGpuSampler(interval_seconds=args.interval) as sampler:
        time.sleep(args.duration)
    write_gpu_csv(args.output, sampler.samples, label=args.label)
    print(f"wrote {len(sampler.samples)} GPU samples to {args.output}")
    return 0 if sampler.samples else 2


if __name__ == "__main__":
    raise SystemExit(main())
