#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
import tomllib
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.conservative_grasp_memory import (
    audit_cross_validated_candidate,
    build_memory_index,
    calibrate_profile_distance_thresholds,
    profile_stratified_group_folds,
    query_memory_evidence,
    select_conservative_memory_candidates,
    select_cross_validated_candidate,
    summarize_conservative_selections,
)
from parcel_sorter.grasp_scoring import sha256_file, validate_feature_names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run train-only group CV for the conservative ROCm grasp memory."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=PROJECT_ROOT / "configs/grasp_memory_v3_cv.toml",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_protocol(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(probability * len(ordered)) - 1)]


def _candidate_parameters(row: Mapping[str, Any], fixed: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "neighbor_count": int(row["neighbor_count"]),
        "distance_quantile": float(row["distance_quantile"]),
        "maximum_static_rank": int(row["maximum_static_rank"]),
        "force_limit_n": float(fixed["force_limit_n"]),
        "minimum_success_ratio": float(fixed["minimum_success_ratio"]),
    }


def _evaluate_candidate(
    torch: Any,
    index: Mapping[str, Any],
    query_rows: list[Mapping[str, Any]],
    parameters: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    thresholds = calibrate_profile_distance_thresholds(
        torch,
        index,
        neighbor_count=int(parameters["neighbor_count"]),
        quantile=float(parameters["distance_quantile"]),
    )
    evidence = query_memory_evidence(
        torch,
        index,
        query_rows,
        neighbor_count=int(parameters["neighbor_count"]),
    )
    selections = select_conservative_memory_candidates(
        query_rows,
        evidence,
        distance_thresholds=thresholds,
        force_limit_n=float(parameters["force_limit_n"]),
        minimum_success_ratio=float(parameters["minimum_success_ratio"]),
        maximum_static_rank=int(parameters["maximum_static_rank"]),
    )
    return selections, thresholds


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol = load_protocol(args.protocol)
    source = protocol["source"]
    folds = protocol["folds"]
    fixed = protocol["fixed"]
    dataset_sha = sha256_file(args.dataset)
    if dataset_sha != str(source["dataset_sha256"]):
        raise ValueError("CV dataset hash differs from the frozen source")
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    validate_feature_names(payload["feature_names"])
    split = str(source["split"])
    rows = [row for row in payload["rows"] if str(row["split"]) == split]
    if len({str(row["group_id"]) for row in rows}) != int(source["expected_groups"]):
        raise ValueError("CV source group count differs from protocol")
    if {str(row["split"]) for row in rows} != {split}:
        raise ValueError("CV rows crossed source splits")
    profiles = tuple(sorted({str(row["profile"]) for row in rows}))
    if profiles != tuple(sorted(str(value) for value in source["expected_profiles"])):
        raise ValueError("CV source profiles differ from protocol")

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for grasp memory CV") from exc
    device_name = str(fixed["device"])
    if device_name == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("AMD ROCm device is unavailable through torch.cuda")
    assignments = profile_stratified_group_folds(
        rows,
        fold_count=int(folds["count"]),
        seed=int(folds["seed"]),
    )
    candidate_rows = list(protocol["candidates"])
    selections_by_candidate: dict[str, list[dict[str, Any]]] = {
        str(row["name"]): [] for row in candidate_rows
    }
    fold_summaries: dict[str, list[dict[str, Any]]] = {
        str(row["name"]): [] for row in candidate_rows
    }
    fold_records = []
    for fold_index in range(int(folds["count"])):
        memory_rows = [
            row for row in rows if assignments[str(row["group_id"])] != fold_index
        ]
        query_rows = [
            row for row in rows if assignments[str(row["group_id"])] == fold_index
        ]
        index = build_memory_index(torch, memory_rows, device=device_name)
        candidate_records = []
        for candidate in candidate_rows:
            name = str(candidate["name"])
            parameters = _candidate_parameters(candidate, fixed)
            selections, thresholds = _evaluate_candidate(
                torch, index, query_rows, parameters
            )
            summary = summarize_conservative_selections(selections)
            selections_by_candidate[name].extend(selections)
            fold_summaries[name].append(summary)
            candidate_records.append(
                {
                    "name": name,
                    "parameters": parameters,
                    "distance_thresholds": thresholds,
                    "summary": summary,
                }
            )
        fold_records.append(
            {
                "fold": fold_index,
                "train_groups": sorted(
                    group_id for group_id, fold in assignments.items() if fold != fold_index
                ),
                "validation_groups": sorted(
                    group_id for group_id, fold in assignments.items() if fold == fold_index
                ),
                "candidates": candidate_records,
            }
        )

    full_index = build_memory_index(torch, rows, device=device_name)
    benchmark_group = str(fixed["latency_group_id"])
    benchmark_rows = [row for row in rows if str(row["group_id"]) == benchmark_group]
    if len(benchmark_rows) != int(fixed["latency_candidate_count"]):
        raise ValueError("latency group does not contain the expected candidate count")
    audits = []
    for candidate in candidate_rows:
        name = str(candidate["name"])
        parameters = _candidate_parameters(candidate, fixed)
        thresholds = calibrate_profile_distance_thresholds(
            torch,
            full_index,
            neighbor_count=int(parameters["neighbor_count"]),
            quantile=float(parameters["distance_quantile"]),
        )

        def benchmark_once() -> None:
            evidence = query_memory_evidence(
                torch,
                full_index,
                benchmark_rows,
                neighbor_count=int(parameters["neighbor_count"]),
            )
            select_conservative_memory_candidates(
                benchmark_rows,
                evidence,
                distance_thresholds=thresholds,
                force_limit_n=float(parameters["force_limit_n"]),
                minimum_success_ratio=float(parameters["minimum_success_ratio"]),
                maximum_static_rank=int(parameters["maximum_static_rank"]),
            )

        for _ in range(int(fixed["latency_warmup"])):
            benchmark_once()
        latencies = []
        for _ in range(int(fixed["latency_repeats"])):
            started = time.perf_counter_ns()
            benchmark_once()
            latencies.append((time.perf_counter_ns() - started) / 1_000_000)
        warm_p95_ms = _percentile(latencies, 0.95)
        summary = summarize_conservative_selections(selections_by_candidate[name])
        audit = audit_cross_validated_candidate(
            name,
            summary,
            fold_summaries[name],
            expected_group_count=int(source["expected_groups"]),
            expected_profile_group_count=int(source["expected_groups_per_profile"]),
            max_warm_p95_ms=float(fixed["max_warm_batch_p95_ms"]),
            warm_p95_ms=warm_p95_ms,
        )
        audit.update(
            {
                "parameters": parameters,
                "latency": {
                    "batch_group_id": benchmark_group,
                    "batch_size": len(benchmark_rows),
                    "warmup": int(fixed["latency_warmup"]),
                    "repeats": int(fixed["latency_repeats"]),
                    "warm_p50_ms": _percentile(latencies, 0.50),
                    "warm_p95_ms": warm_p95_ms,
                },
            }
        )
        audits.append(audit)
    selection = select_cross_validated_candidate(audits)
    return {
        "schema_version": "1.0",
        "claim_boundary": "Train-only grouped cross-validation; no development or holdout row is consumed and no new physics is authorized.",
        "protocol": str(args.protocol.resolve()),
        "protocol_sha256": sha256_file(args.protocol),
        "dataset": str(args.dataset.resolve()),
        "dataset_sha256": dataset_sha,
        "source_split": split,
        "group_count": len(assignments),
        "fold_assignments": assignments,
        "folds": fold_records,
        "device": {
            "requested": device_name,
            "torch_version": torch.__version__,
            "hip_version": torch.version.hip,
            "device_name": torch.cuda.get_device_name(0) if device_name == "cuda" else "cpu",
        },
        "selection": selection,
        "candidates": audits,
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
                "status": result["selection"]["status"],
                "selected": result["selection"]["selected"],
                "new_physics_authorized": result["selection"][
                    "new_physics_authorized"
                ],
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
