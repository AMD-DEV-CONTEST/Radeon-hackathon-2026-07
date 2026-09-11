#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import tomllib
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.conservative_grasp_memory import profile_stratified_group_folds
from parcel_sorter.grasp_scoring import sha256_file, validate_feature_names


def _require(payload: dict[str, Any], path: tuple[str, ...], expected: Any) -> None:
    value: Any = payload
    for key in path:
        value = value[key]
    if value != expected:
        dotted = ".".join(path)
        raise ValueError(f"protocol {dotted} differs: {value!r} != {expected!r}")


def audit_protocol(
    protocol_path: Path,
    *,
    dataset_path: Path | None = None,
) -> dict[str, Any]:
    with protocol_path.open("rb") as stream:
        protocol = tomllib.load(stream)
    _require(protocol, ("metadata", "schema_version"), 1)
    _require(protocol, ("source", "split"), "train")
    _require(protocol, ("source", "expected_groups"), 32)
    _require(protocol, ("source", "expected_groups_per_profile"), 8)
    _require(protocol, ("source", "development_forbidden"), True)
    _require(protocol, ("source", "holdout_forbidden"), True)
    _require(protocol, ("folds", "count"), 4)
    _require(protocol, ("folds", "profile_stratified"), True)
    _require(protocol, ("folds", "group_isolation"), True)
    _require(protocol, ("fixed", "device"), "cuda")
    _require(protocol, ("fixed", "single_gpu"), True)
    _require(protocol, ("fixed", "force_limit_n"), 35.0)
    _require(protocol, ("fixed", "require_zero_unsafe_neighbors"), True)
    _require(protocol, ("fixed", "fallback"), "static_geometry_first_choice")
    _require(protocol, ("fixed", "require_no_per_profile_safety_regression"), True)
    _require(protocol, ("fixed", "require_no_per_fold_safety_regression"), True)
    _require(protocol, ("fixed", "require_aggregate_task_or_safety_improvement"), True)
    _require(protocol, ("stopping", "no_cv_candidate_if_all_fail"), True)
    _require(
        protocol,
        ("stopping", "do_not_inspect_v2_development_for_threshold_selection"),
        True,
    )
    _require(protocol, ("stopping", "do_not_open_v2_holdout"), True)
    _require(
        protocol,
        ("stopping", "new_v3_physics_requires_separate_frozen_population"),
        True,
    )
    expected_profiles = tuple(
        sorted(str(value) for value in protocol["source"]["expected_profiles"])
    )
    if len(expected_profiles) != 4 or len(set(expected_profiles)) != 4:
        raise ValueError("protocol requires four unique expected profiles")
    source_hash = str(protocol["source"]["dataset_sha256"])
    if len(source_hash) != 64:
        raise ValueError("source dataset SHA-256 is malformed")

    implementation_hashes = {}
    implementation = protocol["implementation"]
    for name in ("memory", "runner", "features"):
        path = PROJECT_ROOT / str(implementation[name])
        expected = str(implementation[f"{name}_sha256"])
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"implementation hash differs for {name}: {actual}")
        implementation_hashes[name] = actual

    candidates = list(protocol.get("candidates", ()))
    names = [str(row["name"]) for row in candidates]
    if not candidates or len(names) != len(set(names)):
        raise ValueError("CV candidates must be nonempty and uniquely named")
    for row in candidates:
        if int(row["neighbor_count"]) < 1:
            raise ValueError("candidate neighbor_count must be positive")
        if int(row["maximum_static_rank"]) < 0:
            raise ValueError("candidate maximum_static_rank must be non-negative")
        if not 0 < float(row["distance_quantile"]) <= 1:
            raise ValueError("candidate distance_quantile must be in (0, 1]")

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "protocol_valid",
        "protocol": str(protocol_path.resolve()),
        "protocol_sha256": sha256_file(protocol_path),
        "source_dataset_sha256": source_hash,
        "implementation_hashes": implementation_hashes,
        "candidate_names": names,
        "fold_count": int(protocol["folds"]["count"]),
        "development_forbidden": True,
        "holdout_forbidden": True,
        "dataset_observed": dataset_path is not None,
    }
    if dataset_path is not None:
        if sha256_file(dataset_path) != source_hash:
            raise ValueError("observed CV dataset hash differs from protocol")
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        validate_feature_names(dataset["feature_names"])
        rows = [
            row
            for row in dataset["rows"]
            if str(row["split"]) == str(protocol["source"]["split"])
        ]
        assignments = profile_stratified_group_folds(
            rows,
            fold_count=int(protocol["folds"]["count"]),
            seed=int(protocol["folds"]["seed"]),
        )
        if len(assignments) != int(protocol["source"]["expected_groups"]):
            raise ValueError("observed CV group count differs from protocol")
        profiles_by_group = {
            str(row["group_id"]): str(row["profile"]) for row in rows
        }
        fold_profile_counts = {
            str(fold): dict(
                sorted(
                    Counter(
                        profiles_by_group[group_id]
                        for group_id, assigned in assignments.items()
                        if assigned == fold
                    ).items()
                )
            )
            for fold in range(int(protocol["folds"]["count"]))
        }
        expected_per_fold = int(protocol["source"]["expected_groups_per_profile"]) // int(
            protocol["folds"]["count"]
        )
        if any(
            tuple(sorted(counts)) != expected_profiles
            or any(value != expected_per_fold for value in counts.values())
            for counts in fold_profile_counts.values()
        ):
            raise ValueError("observed CV folds are not profile balanced")
        result.update(
            {
                "dataset_observed": True,
                "group_count": len(assignments),
                "fold_profile_counts": fold_profile_counts,
                "fold_assignments": assignments,
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the frozen train-only conservative grasp-memory CV protocol."
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=PROJECT_ROOT / "configs/grasp_memory_v3_cv.toml",
    )
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_protocol(
        args.protocol.resolve(),
        dataset_path=args.dataset.resolve() if args.dataset else None,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
