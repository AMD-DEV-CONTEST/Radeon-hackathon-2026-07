"""Measure a reproducible, fully local perception run for competition evidence.

Example:
  python scripts/benchmark_runtime.py --video videos/demo.mp4 \
    --corners "120,650 1800,640 1850,720 80,730"
"""

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fencing_analysis.pipeline import run_pipeline
from fencing_analysis.piste.mapper import parse_corners_arg


def main():
    ap = argparse.ArgumentParser(description="Benchmark SparkFencer local perception")
    ap.add_argument("--video", required=True)
    ap.add_argument("--corners", required=True)
    ap.add_argument("--piste-length", type=float, default=14.0)
    ap.add_argument("--output-dir", default="outputs/benchmark_local")
    args = ap.parse_args()

    started = time.perf_counter()
    result = run_pipeline(
        args.video, corners=parse_corners_arg(args.corners), output_dir=args.output_dir,
        config_path=os.path.join(ROOT, "config.yaml"),
        config_overrides={"piste": {"length": args.piste_length}},
        stages=("perception",), skip_agents=True,
    )
    elapsed = time.perf_counter() - started
    metadata_path = result["perception"]["metadata"]
    with open(metadata_path, encoding="utf-8") as f:
        metadata = json.load(f)
    report = {
        "local_only": True,
        "elapsed_sec": round(elapsed, 3),
        "frames": metadata["video"]["total_frames"],
        "fps": round(metadata["video"]["total_frames"] / elapsed, 3) if elapsed else None,
        "models": metadata["models"],
        "output_dir": args.output_dir,
    }
    path = os.path.join(args.output_dir, "benchmark.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
