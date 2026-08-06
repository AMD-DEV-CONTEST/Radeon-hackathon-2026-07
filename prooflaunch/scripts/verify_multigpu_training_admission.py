#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


SCHEMA = "ProofLaunchGemma4EmotionDistributedTrainingV1"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"{path}: unexpected schema")
    receipts = payload.get("hardware", {}).get("rank_receipts", [])
    world_size = payload.get("hardware", {}).get("world_size")
    if len(receipts) != world_size:
        raise ValueError(f"{path}: incomplete rank-receipt list")
    for expected_rank, record in enumerate(receipts):
        if record.get("rank") != expected_rank:
            raise ValueError(f"{path}: non-contiguous rank receipt")
        receipt_path = (
            path.parent
            / "distributed-ranks"
            / Path(record["path"]).name
        )
        raw = receipt_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record.get("sha256"):
            raise ValueError(f"{path}: rank receipt hash mismatch")
        receipt = json.loads(raw)
        if (
            receipt.get("global_rank") != expected_rank
            or not receipt.get("training_complete")
        ):
            raise ValueError(f"{path}: rank receipt is incomplete")
    return payload


def _frozen_comparison_contract(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_id": payload["model"]["id"],
        "model_revision": payload["model"]["revision"],
        "dataset_id": payload["dataset"]["id"],
        "dataset_revision": payload["dataset"]["revision"],
        "train_count": payload["dataset"]["train_count"],
        "validation_count": payload["dataset"]["validation_count"],
        "run_profile": payload["optimization"]["run_profile"],
        "seed": payload["optimization"]["seed"],
        "dtype": payload["optimization"]["dtype"],
        "attention": payload["optimization"]["attention"],
        "effective_global_batch_size": payload["optimization"][
            "effective_global_batch_size"
        ],
        "lora_rank": payload["optimization"]["lora_rank"],
        "lora_target_count": payload["optimization"][
            "lora_target_count"
        ],
    }


def _positive_metric(payload: dict[str, Any], key: str) -> float:
    value = payload["train_metrics"].get(key)
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"missing positive train metric {key}")
    return float(value)


def _eval_loss(payload: dict[str, Any]) -> float:
    value = payload["final_validation_metrics"].get("eval_loss")
    if not isinstance(value, (int, float)) or value < 0:
        raise ValueError("missing final non-negative eval_loss")
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single-manifest", type=Path, required=True)
    parser.add_argument(
        "--multi-manifest",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-repeats", type=int, default=3)
    parser.add_argument("--minimum-speedup", type=float, default=1.5)
    parser.add_argument(
        "--minimum-parallel-efficiency",
        type=float,
        default=0.70,
    )
    parser.add_argument(
        "--maximum-relative-eval-loss-regression",
        type=float,
        default=0.02,
    )
    args = parser.parse_args()

    single = _load(args.single_manifest)
    multi = [_load(path) for path in args.multi_manifest]
    blockers: list[str] = []
    if single["hardware"]["world_size"] != 1:
        blockers.append("single_baseline_world_size")
    if single["hardware"]["parallelism"] != "single":
        blockers.append("single_baseline_parallelism")
    if len(multi) < args.minimum_repeats:
        blockers.append("insufficient_multi_gpu_repeats")

    reference = _frozen_comparison_contract(single)
    if any(_frozen_comparison_contract(item) != reference for item in multi):
        blockers.append("comparison_contract_drift")
    world_sizes = {item["hardware"]["world_size"] for item in multi}
    if len(world_sizes) != 1 or not world_sizes or min(world_sizes) < 2:
        blockers.append("invalid_or_mixed_multi_gpu_world_size")
        world_size = 0
    else:
        world_size = next(iter(world_sizes))

    single_throughput = _positive_metric(
        single, "train_samples_per_second"
    )
    multi_throughputs = [
        _positive_metric(item, "train_samples_per_second")
        for item in multi
    ]
    speedups = [
        throughput / single_throughput
        for throughput in multi_throughputs
    ]
    median_speedup = statistics.median(speedups)
    parallel_efficiency = (
        median_speedup / world_size if world_size else 0.0
    )
    if median_speedup < args.minimum_speedup:
        blockers.append("speedup_below_floor")
    if parallel_efficiency < args.minimum_parallel_efficiency:
        blockers.append("parallel_efficiency_below_floor")

    single_loss = _eval_loss(single)
    multi_losses = [_eval_loss(item) for item in multi]
    median_multi_loss = statistics.median(multi_losses)
    relative_loss_regression = (
        (median_multi_loss - single_loss) / max(single_loss, 1e-12)
    )
    if (
        relative_loss_regression
        > args.maximum_relative_eval_loss_regression
    ):
        blockers.append("eval_loss_regression")

    report = {
        "schema": "ProofLaunchMultiGpuTrainingAdmissionV1",
        "status": "passed" if not blockers else "blocked",
        "frozen_comparison_contract": reference,
        "world_size": world_size,
        "repeat_count": len(multi),
        "single_train_samples_per_second": single_throughput,
        "multi_train_samples_per_second": multi_throughputs,
        "speedups": speedups,
        "median_speedup": median_speedup,
        "parallel_efficiency": parallel_efficiency,
        "single_eval_loss": single_loss,
        "multi_eval_losses": multi_losses,
        "median_multi_eval_loss": median_multi_loss,
        "relative_eval_loss_regression": relative_loss_regression,
        "thresholds": {
            "minimum_repeats": args.minimum_repeats,
            "minimum_speedup": args.minimum_speedup,
            "minimum_parallel_efficiency": (
                args.minimum_parallel_efficiency
            ),
            "maximum_relative_eval_loss_regression": (
                args.maximum_relative_eval_loss_regression
            ),
        },
        "blockers": blockers,
        "truth_boundary": (
            "This compares the supplied immutable single- and multi-GPU "
            "training receipts. It does not replace image/audio retention, "
            "multi-seed quality, human 4A review, or competition outcomes."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
