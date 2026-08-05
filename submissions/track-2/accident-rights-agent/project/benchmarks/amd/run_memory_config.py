#!/usr/bin/env python3
"""Run one frozen AMD configuration against one frozen case payload."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.amd.common import run_request, summarize_runs, write_gpu_csv  # noqa: E402
from experiments.memory.gpu import AmdGpuSampler  # noqa: E402
from experiments.memory.streaming import model_name  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu-csv", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=6)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.requests < args.concurrency or args.concurrency < 1:
        parser.error("requests must be >= concurrency >= 1")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    barrier = threading.Barrier(args.concurrency)

    def worker(index: int) -> dict[str, object]:
        barrier.wait(timeout=60)
        return {"request_index": index, **run_request(payload, max_tokens=args.max_tokens)}

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    with AmdGpuSampler(interval_seconds=0.5) as sampler:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            runs = list(executor.map(worker, range(args.requests)))
    wall_seconds = time.perf_counter() - started
    summary = summarize_runs(runs, wall_seconds)
    summary["gpu"] = sampler.summary()
    config_record = (
        json.loads(args.config.read_text(encoding="utf-8"))
        if args.config
        else {}
    )
    config = config_record.get("config", config_record)
    result = {
        "schema_version": 1,
        "label": args.label,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model_name(),
        "input": str(args.input),
        "max_tokens": args.max_tokens,
        "concurrency": args.concurrency,
        "config": config,
        "summary": summary,
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_gpu_csv(args.gpu_csv, sampler.samples, label=args.label)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["success_rate"] >= 0.95 and summary["oom_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
