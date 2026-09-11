#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.grasp_scoring import (
    evaluate_ranked_grasp_predictions,
    sha256_file,
    validate_feature_names,
)
from parcel_sorter.grasp_scorer_model import StructuredGraspScorer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate a structured grasp scorer checkpoint without controller integration."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--benchmark-repeats", type=int, default=100)
    parser.add_argument(
        "--latency-group-id",
        help="benchmark one real candidate group while evaluating the complete split",
    )
    return parser.parse_args()


def latency_rows(
    rows: list[dict[str, Any]],
    group_id: str | None,
) -> list[dict[str, Any]]:
    if group_id is None:
        return rows
    selected = [row for row in rows if str(row["group_id"]) == group_id]
    if not selected:
        raise ValueError(
            f"latency group is absent from the evaluation split: {group_id}"
        )
    return selected


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.warmup < 0 or args.benchmark_repeats < 1:
        raise ValueError("warmup must be non-negative and benchmark repeats positive")
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    validate_feature_names(dataset["feature_names"])
    rows: list[dict[str, Any]] = [
        row for row in dataset["rows"] if str(row["split"]) == args.split
    ]
    if not rows:
        raise ValueError(f"dataset contains no rows for split {args.split}")
    scorer = StructuredGraspScorer(args.checkpoint, device=args.device)
    features = [row["features"] for row in rows]
    metadata = [
        {"candidate_id": row["candidate_id"], "static_rank": row["static_rank"]}
        for row in rows
    ]
    benchmark_rows = latency_rows(rows, args.latency_group_id)
    benchmark_features = [row["features"] for row in benchmark_rows]
    benchmark_metadata = [
        {"candidate_id": row["candidate_id"], "static_rank": row["static_rank"]}
        for row in benchmark_rows
    ]
    cold_started = time.perf_counter_ns()
    scorer.predict(benchmark_features, benchmark_metadata)
    cold_ms = (time.perf_counter_ns() - cold_started) / 1_000_000
    predictions = scorer.predict(features, metadata)
    for _ in range(args.warmup):
        scorer.predict(benchmark_features, benchmark_metadata)
    latencies_ms: list[float] = []
    for _ in range(args.benchmark_repeats):
        started = time.perf_counter_ns()
        scorer.predict(benchmark_features, benchmark_metadata)
        latencies_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(latencies_ms)
    p50_ms = ordered[math.ceil(0.50 * len(ordered)) - 1]
    p95_ms = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return {
        "schema_version": 1,
        "claim_boundary": "Offline checkpoint evaluation; controller integration remains disabled.",
        "dataset": str(args.dataset.resolve()),
        "dataset_sha256": sha256_file(args.dataset),
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_sha256": sha256_file(args.checkpoint),
        "split": args.split,
        "row_count": len(rows),
        "device": args.device,
        "latency": {
            "batch_group_id": args.latency_group_id,
            "batch_size": len(benchmark_rows),
            "warmup": args.warmup,
            "benchmark_repeats": args.benchmark_repeats,
            "cold_batch_ms": cold_ms,
            "steady_batch_p50_ms": p50_ms,
            "steady_batch_p95_ms": p95_ms,
            "steady_per_candidate_p50_ms": p50_ms / len(benchmark_rows),
            "steady_per_candidate_p95_ms": p95_ms / len(benchmark_rows),
        },
        "evaluation": evaluate_ranked_grasp_predictions(rows, predictions),
        "predictions": predictions,
    }


def main() -> int:
    args = parse_args()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "row_count": result["row_count"],
                "latency": result["latency"],
                "evaluation": result["evaluation"],
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
