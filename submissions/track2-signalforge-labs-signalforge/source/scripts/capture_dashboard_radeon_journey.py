#!/usr/bin/env python3
"""Capture a privacy-safe aggregate from one completed Radeon Workspace journey."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "signalforge/dashboard-radeon-journey/v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def build_journey(
    run: dict[str, Any],
    intelligence: dict[str, Any],
    trace_path: Path,
    mode: str,
) -> dict[str, Any]:
    if mode not in {"local_only", "hybrid_radeon_api"}:
        raise ValueError("unsupported Radeon journey mode")
    if run.get("status") != "completed":
        raise ValueError("only completed journeys may be published")
    if intelligence.get("status") != "completed":
        raise ValueError("intelligence lineage is not complete")
    if run.get("run_id") != intelligence.get("run_id"):
        raise ValueError("run identity mismatch")
    if run.get("trace_id") != intelligence.get("trace_id"):
        raise ValueError("trace identity mismatch")
    if intelligence.get("release", {}).get("status") != "released":
        raise ValueError("journey was not released")

    plan = run.get("execution_plan")
    if not isinstance(plan, dict) or plan.get("status") != "passed":
        raise ValueError("execution plan did not pass")
    calls = intelligence.get("model_calls")
    if not isinstance(calls, list) or not calls:
        raise ValueError("journey contains no model calls")

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "run_id": run["run_id"],
        "trace_id": run["trace_id"],
        "status": run["status"],
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "source_trace_sha256": sha256_file(trace_path),
        "execution_plan": {
            "schema_version": plan.get("schema_version"),
            "plan_id": plan.get("plan_id"),
            "status": plan.get("status"),
            "total_steps": plan.get("total_steps"),
            "terminal_steps": plan.get("terminal_steps"),
            "progress_ratio": plan.get("progress_ratio"),
            "max_parallel_specialists": plan.get("max_parallel_specialists"),
            "route_summary": sorted(set(plan.get("route_summary") or [])),
            "projection_sha256": plan.get("projection_sha256"),
            "phases": [
                {"phase_id": phase.get("phase_id"), "status": phase.get("status")}
                for phase in plan.get("phases", [])
            ],
        },
        "intelligence": {
            "schema_version": intelligence.get("schema_version"),
            "capture_status": intelligence.get("capture", {}).get("status"),
            "release_status": intelligence.get("release", {}).get("status"),
            "model_calls": len(calls),
            "context_packets": len(intelligence.get("retrievals") or []),
            "engine_receipts": len(intelligence.get("engine_calls") or []),
            "reviews": len(intelligence.get("reviews") or []),
            "input_tokens": sum(int(call.get("input_tokens") or 0) for call in calls),
            "output_tokens": sum(int(call.get("output_tokens") or 0) for call in calls),
            "providers": sorted({str(call.get("provider_id")) for call in calls if call.get("provider_id")}),
            "routes": sorted({str(call.get("route")) for call in calls if call.get("route")}),
            "roles": sorted({str(call.get("role_id")) for call in calls if call.get("role_id")}),
        },
        "privacy": {
            "credentials_retained": False,
            "prompt_bodies_retained": False,
            "response_bodies_retained": False,
            "source_bodies_retained": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--mode", choices=["local_only", "hybrid_radeon_api"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    run = load_json(f"{base_url}/api/v1/runs/{args.run_id}")
    intelligence = load_json(f"{base_url}/api/v1/runs/{args.run_id}/intelligence")
    journey = build_journey(run, intelligence, args.trace, args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(journey, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": journey["run_id"], "status": journey["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
