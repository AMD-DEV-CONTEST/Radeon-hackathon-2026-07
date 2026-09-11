#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.grasp_scoring import sha256_file


EXPECTED_IMPLEMENTATION_KEYS = (
    ("trainer", "trainer_sha256"),
    ("evaluator", "evaluator_sha256"),
    ("selector", "selector_sha256"),
    ("model", "model_sha256"),
    ("features_and_metrics", "features_and_metrics_sha256"),
    ("promotion_gate", "promotion_gate_sha256"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit the frozen v2 grasp scorer model-selection protocol."
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=PROJECT_ROOT / "configs/grasp_candidate_model_selection_v2.toml",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def audit_protocol(protocol_path: Path) -> dict[str, Any]:
    protocol_path = protocol_path.resolve()
    with protocol_path.open("rb") as stream:
        protocol = tomllib.load(stream)
    source = protocol["source"]
    implementation = protocol["implementation"]
    training = protocol["common_training"]
    development = protocol["development"]
    holdout = protocol["holdout"]
    stopping = protocol["stopping"]

    collection_path = PROJECT_ROOT / str(source["collection_protocol"])
    _require(
        sha256_file(collection_path) == source["collection_protocol_sha256"],
        "collection protocol hash differs",
    )
    implementation_hashes = {}
    for path_key, hash_key in EXPECTED_IMPLEMENTATION_KEYS:
        path = PROJECT_ROOT / str(implementation[path_key])
        observed = sha256_file(path)
        _require(observed == implementation[hash_key], f"{path_key} hash differs")
        implementation_hashes[path_key] = observed

    _require(training["device"] == "cuda", "training device must be cuda/ROCm")
    _require(training["single_gpu"] is True, "training must use one GPU")
    _require(training["parameter_count"] == 6276, "model capacity must stay fixed")
    _require(
        training["checkpoint_frozen_before_development"] is True,
        "checkpoints must freeze before development",
    )
    candidates = protocol["candidates"]
    _require(
        [row["name"] for row in candidates]
        == ["pointwise", "groupwise-safety-first"],
        "candidate set or order differs",
    )
    _require(
        candidates[1]["safety_pair_weight"] == 2.0
        and candidates[1]["success_pair_weight"] == 1.0,
        "groupwise loss weights differ",
    )
    _require(
        development["expected_group_count"] == 16
        and development["expected_profile_group_count"] == 4,
        "development sample size differs",
    )
    _require(
        development["require_no_per_profile_safety_regression"] is True,
        "per-profile safety gate is disabled",
    )
    _require(
        development["require_aggregate_task_or_safety_improvement"] is True,
        "aggregate improvement gate is disabled",
    )
    _require(
        development["max_warm_batch_p95_ms"] == 5.0,
        "Radeon latency gate differs",
    )
    _require(holdout["locked"] is True, "holdout is not locked")
    _require(
        holdout["execute_once_after_selection"] is True,
        "holdout is not one-shot",
    )
    _require(
        stopping["no_promotion_if_all_candidates_fail"] is True
        and stopping["do_not_tune_on_development_after_failure"] is True,
        "negative-result stopping rule is disabled",
    )
    return {
        "schema_version": "1.0",
        "status": "passed",
        "protocol": str(protocol_path),
        "protocol_sha256": sha256_file(protocol_path),
        "collection_protocol_sha256": source["collection_protocol_sha256"],
        "implementation_hashes": implementation_hashes,
        "candidate_names": [row["name"] for row in candidates],
        "parameter_count": training["parameter_count"],
        "development_group_count": development["expected_group_count"],
        "max_warm_batch_p95_ms": development["max_warm_batch_p95_ms"],
        "holdout_locked": True,
    }


def main() -> int:
    args = parse_args()
    result = audit_protocol(args.protocol)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
