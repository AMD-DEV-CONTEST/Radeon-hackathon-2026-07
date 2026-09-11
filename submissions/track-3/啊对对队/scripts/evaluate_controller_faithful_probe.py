#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import tomllib
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.conservative_grasp_memory import profile_stratified_group_folds
from parcel_sorter.controller_faithful_probe import (
    PROBE_POLICIES,
    audit_controller_faithful_probe_candidate,
    build_controller_faithful_probe_dataset,
    select_controller_faithful_probe_policy,
    summarize_controller_faithful_probe,
    select_controller_faithful_probe_candidate,
)
from parcel_sorter.grasp_scoring import sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate fixed controller-faithful pre-place probe policies on train only."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--dataset-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_protocol(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("probe protocol must be a TOML table")
    return payload


def manifest_sources(
    manifest_path: Path,
    *,
    protocol: Mapping[str, Any],
) -> list[tuple[str, dict[str, Any], str, str]]:
    manifest = _load_json(manifest_path)
    source = protocol["source"]
    if str(manifest.get("split")) != str(source["split"]):
        raise ValueError("probe manifest split differs from frozen protocol")
    if str(manifest.get("protocol_sha256")) != str(source["collection_protocol_sha256"]):
        raise ValueError("probe manifest collection protocol differs")
    rows = manifest.get("runs")
    if not isinstance(rows, list) or not rows:
        raise ValueError("probe manifest contains no runs")
    sources = []
    for item in rows:
        if not isinstance(item, Mapping):
            raise ValueError("probe manifest run is not a mapping")
        if str(item.get("status")) not in {"complete", "reused"}:
            raise ValueError("probe manifest contains an incomplete run")
        if str(item.get("source_status")) != "complete":
            raise ValueError("probe manifest run has no complete source")
        path = Path(str(item["output"]))
        if not path.is_file():
            raise ValueError(f"probe source is missing: {path}")
        source_sha256 = sha256_file(path)
        if source_sha256 != str(item.get("sha256")):
            raise ValueError(f"probe source hash differs from manifest: {path}")
        payload = _load_json(path)
        if str(payload.get("split", source["split"])) not in {
            str(source["split"]),
            "",
        }:
            raise ValueError(f"probe source has an unexpected split: {path}")
        sources.append((str(path), payload, source_sha256, str(source["split"])))
    return sources


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * probability)))
    return float(ordered[index])


def _policy_summary(
    rows: list[Mapping[str, Any]],
    policy: str,
    assignments: Mapping[str, int],
    fold_count: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    all_selections = select_controller_faithful_probe_policy(rows, policy=policy)
    by_group = {str(row["group_id"]): row for row in all_selections}
    fold_summaries = []
    for fold_index in range(fold_count):
        fold_selections = [
            by_group[group_id]
            for group_id, assigned in sorted(assignments.items())
            if assigned == fold_index
        ]
        fold_summaries.append(summarize_controller_faithful_probe(fold_selections))
    return summarize_controller_faithful_probe(all_selections), fold_summaries


def _benchmark_policy(
    rows: list[Mapping[str, Any]],
    policy: str,
    *,
    group_id: str,
    warmup: int,
    repeats: int,
) -> dict[str, Any]:
    batch = [row for row in rows if str(row["group_id"]) == group_id]
    if not batch:
        raise ValueError(f"latency group is absent: {group_id}")
    for _ in range(warmup):
        select_controller_faithful_probe_policy(batch, policy=policy)
    latencies = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        select_controller_faithful_probe_policy(batch, policy=policy)
        latencies.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "group_id": group_id,
        "batch_size": len(batch),
        "warmup": warmup,
        "repeats": repeats,
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol = _load_protocol(args.protocol)
    metadata = protocol["metadata"]
    source = protocol["source"]
    fixed = protocol["fixed"]
    if str(metadata["protocol_id"]) != "controller-faithful-probe-v4-train-only":
        raise ValueError("unexpected controller-faithful probe protocol id")
    protocol_sha256 = sha256_file(args.protocol)
    if str(args.manifest) != str(source["manifest"]):
        raise ValueError("probe manifest path differs from the frozen protocol")
    if sha256_file(args.manifest) != str(source["manifest_sha256"]):
        raise ValueError("probe manifest hash differs from frozen source")

    sources = manifest_sources(args.manifest, protocol=protocol)
    dataset = build_controller_faithful_probe_dataset(sources)
    if int(dataset["group_count"]) != int(source["expected_groups"]):
        raise ValueError("probe dataset group count differs from protocol")
    if dataset["splits"] != [str(source["split"])]:
        raise ValueError("probe dataset includes a forbidden split")
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    args.dataset_output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    rows = list(dataset["rows"])
    assignments = profile_stratified_group_folds(
        rows,
        fold_count=int(fixed["fold_count"]),
        seed=int(fixed["fold_seed"]),
    )
    profiles = tuple(sorted({str(row["profile"]) for row in rows}))
    expected_profiles = tuple(sorted(str(value) for value in source["expected_profiles"]))
    if profiles != expected_profiles:
        raise ValueError("probe dataset profiles differ from protocol")

    audits = []
    candidate_records = []
    for policy in tuple(str(value) for value in fixed["policies"]):
        summary, fold_summaries = _policy_summary(
            rows,
            policy,
            assignments,
            int(fixed["fold_count"]),
        )
        latency = _benchmark_policy(
            rows,
            policy,
            group_id=str(fixed["latency_group_id"]),
            warmup=int(fixed["latency_warmup"]),
            repeats=int(fixed["latency_repeats"]),
        )
        audit = audit_controller_faithful_probe_candidate(
            policy,
            summary,
            fold_summaries,
            expected_group_count=int(source["expected_groups"]),
            expected_profile_group_count=int(source["expected_groups_per_profile"]),
            max_selection_p95_ms=float(fixed["max_selection_p95_ms"]),
            selection_p95_ms=float(latency["p95_ms"]),
        )
        audit["latency"] = latency
        audits.append(audit)
        candidate_records.append(
            {
                "name": policy,
                "summary": summary,
                "fold_summaries": fold_summaries,
                "latency": latency,
            }
        )

    selection = select_controller_faithful_probe_candidate(audits)
    return {
        "schema_version": "1.0",
        "claim_boundary": str(metadata["claim_boundary"]),
        "protocol": str(args.protocol.resolve()),
        "protocol_sha256": protocol_sha256,
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": sha256_file(args.manifest),
        "dataset": str(args.dataset_output.resolve()),
        "dataset_sha256": sha256_file(args.dataset_output),
        "source_split": str(source["split"]),
        "group_count": len(assignments),
        "fold_assignments": assignments,
        "fold_count": int(fixed["fold_count"]),
        "source_artifact_count": len(sources),
        "policies": candidate_records,
        "audits": audits,
        "selection": selection,
        "holdout_opened": False,
        "new_physics_authorized": False,
        "device": {
            "physics_rollout_device": "AMD Radeon / ROCm",
            "selector_device": "host control logic; no model training in this feasibility stage",
        },
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
                "new_physics_authorized": result["new_physics_authorized"],
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
