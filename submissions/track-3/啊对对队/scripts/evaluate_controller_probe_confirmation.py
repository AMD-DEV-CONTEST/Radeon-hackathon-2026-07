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

from parcel_sorter.controller_probe_confirmation import (
    CONFIRMATION_ACTIVATION_POLICY,
    CONFIRMATION_POLICY,
    CONFIRMATION_SPLIT,
    audit_confirmation,
    build_confirmation_dataset,
    select_veto_static,
    summarize_confirmation,
)
from parcel_sorter.grasp_scoring import sha256_file


PROTOCOL_ID = "controller-faithful-probe-v5-independent-confirmation"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_protocol(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if str(payload["metadata"]["protocol_id"]) != PROTOCOL_ID:
        raise ValueError("unexpected controller probe confirmation protocol id")
    return payload


def manifest_sources(
    manifest_path: Path,
    *,
    protocol_path: Path,
) -> list[tuple[str, dict[str, Any], str]]:
    manifest = _load_json(manifest_path)
    if str(manifest.get("split")) != CONFIRMATION_SPLIT:
        raise ValueError("confirmation manifest has the wrong split")
    if str(manifest.get("protocol_sha256")) != sha256_file(protocol_path):
        raise ValueError("confirmation manifest is not bound to this protocol")
    if str(manifest.get("planning_activation_policy")) != CONFIRMATION_ACTIVATION_POLICY:
        raise ValueError("confirmation manifest has the wrong activation policy")
    rows = manifest.get("runs")
    if not isinstance(rows, list) or not rows:
        raise ValueError("confirmation manifest contains no runs")
    sources: list[tuple[str, dict[str, Any], str]] = []
    for item in rows:
        if not isinstance(item, Mapping):
            raise ValueError("confirmation manifest run is not a mapping")
        if str(item.get("status")) not in {"complete", "reused"}:
            raise ValueError("confirmation manifest contains an incomplete run")
        if str(item.get("source_status")) != "complete":
            raise ValueError("confirmation manifest run has no complete source")
        source_path = Path(str(item["output"]))
        if not source_path.is_file():
            raise ValueError(f"confirmation source is missing: {source_path}")
        source_hash = sha256_file(source_path)
        if source_hash != str(item.get("sha256")):
            raise ValueError(f"confirmation source hash differs from manifest: {source_path}")
        sources.append((str(source_path), _load_json(source_path), source_hash))
    return sources


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * probability)))
    return float(ordered[index])


def _benchmark(
    rows: list[Mapping[str, Any]],
    *,
    group_id: str,
    warmup: int,
    repeats: int,
) -> dict[str, Any]:
    batch = [row for row in rows if str(row["group_id"]) == group_id]
    if not batch:
        raise ValueError(f"latency group is absent: {group_id}")
    for _ in range(warmup):
        select_veto_static(batch)
    timings = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        select_veto_static(batch)
        timings.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "group_id": group_id,
        "batch_size": len(batch),
        "warmup": warmup,
        "repeats": repeats,
        "p50_ms": _percentile(timings, 0.50),
        "p95_ms": _percentile(timings, 0.95),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol = _load_protocol(args.protocol)
    source = protocol["source"]
    population = protocol["population"]
    gates = protocol["gates"]
    fixed = protocol["fixed"]
    if str(args.manifest) != str(source["manifest"]):
        raise ValueError("manifest path differs from the frozen protocol")
    sources = manifest_sources(args.manifest, protocol_path=args.protocol)
    legacy_profiles = frozenset(str(value) for value in population["legacy_profiles"])
    dataset = build_confirmation_dataset(sources, legacy_profiles=legacy_profiles)
    expected_profiles = sorted(str(value) for value in population["profile_ids"])
    if dataset["profiles"] != expected_profiles:
        raise ValueError("confirmation profiles differ from the frozen population")
    if int(dataset["group_count"]) != int(population["expected_groups"]):
        raise ValueError("confirmation group count differs from the frozen population")
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    args.dataset_output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    rows = list(dataset["rows"])
    selections = select_veto_static(rows)
    summary = summarize_confirmation(selections)
    latency = _benchmark(
        rows,
        group_id=str(fixed["latency_group_id"]),
        warmup=int(fixed["latency_warmup"]),
        repeats=int(fixed["latency_repeats"]),
    )
    decision = audit_confirmation(
        summary,
        expected_groups=int(population["expected_groups"]),
        expected_groups_per_profile=int(population["episodes_per_profile"]),
        min_safety_abort_reductions=int(gates["min_safety_abort_reductions"]),
        min_profiles_with_safety_reduction=int(gates["min_profiles_with_safety_reduction"]),
        safety_alpha=float(gates["safety_one_sided_alpha"]),
        selection_p95_ms=float(latency["p95_ms"]),
        max_selection_p95_ms=float(gates["max_selection_p95_ms"]),
    )
    return {
        "schema_version": "1.0",
        "claim_boundary": str(protocol["metadata"]["claim_boundary"]),
        "protocol": str(args.protocol.resolve()),
        "protocol_sha256": sha256_file(args.protocol),
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": sha256_file(args.manifest),
        "dataset": str(args.dataset_output.resolve()),
        "dataset_sha256": sha256_file(args.dataset_output),
        "source_artifact_count": len(sources),
        "policy": CONFIRMATION_POLICY,
        "summary": summary,
        "latency": latency,
        "decision": decision,
        "device": {
            "physics_rollout_device": "single AMD Radeon / ROCm",
            "offline_selector_device": "host control logic",
            "online_parallel_probe_status": "not_run",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the frozen V5 veto-static confirmation population.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--dataset-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **result["decision"]}, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
