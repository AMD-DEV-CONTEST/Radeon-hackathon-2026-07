#!/usr/bin/env python3
"""Prepare and audit one non-executing Harness Agent improvement cycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parcel_sorter.checkpoint_registry import sha256_file
from parcel_sorter.harness_agent import (
    HarnessAgentConfig,
    RuleBasedFailureAnalyst,
    build_failure_packet,
    quarantine_correction,
    sha256_json,
    training_admission_gate,
    verify_replayed_correction,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build quarantined Agent corrections from failed episodes and optionally "
            "admit independently replayed successes. This command never executes a "
            "robot action or activates a checkpoint."
        )
    )
    parser.add_argument("--source-campaign-audit", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--replay-audits",
        type=Path,
        help="optional JSON with a runs list keyed by candidate_id",
    )
    args = parser.parse_args()

    source = _read_json(args.source_campaign_audit)
    config_payload = _read_json(args.config)
    config = HarnessAgentConfig.from_dict(config_payload)
    analyst = RuleBasedFailureAnalyst(config.failure_analyst)
    replay_by_candidate = _load_replays(args.replay_audits)
    runs = source.get("runs")
    if not isinstance(runs, list):
        raise ValueError("source campaign audit must contain a runs list")

    source_sha = sha256_file(args.source_campaign_audit)
    records = []
    for run in runs:
        if not isinstance(run, dict) or bool(run.get("success")):
            continue
        packet = build_failure_packet(run, source_audit_sha256=source_sha)
        analysis = dict(analyst.analyze(packet))
        candidate = quarantine_correction(
            packet, analysis, analyst=config.failure_analyst
        )
        replay = replay_by_candidate.get(str(candidate["candidate_id"]))
        verification = None
        admission = None
        if replay is not None:
            verification = verify_replayed_correction(
                candidate,
                replay,
                verifier=config.independent_verifier,
                config=config,
            )
            admission = training_admission_gate(candidate, verification)
        records.append(
            {
                "failure_packet": packet,
                "analysis": analysis,
                "candidate": candidate,
                "replay_audit": replay,
                "verification": verification,
                "admission": admission,
            }
        )

    payload = {
        "schema_version": 1,
        "protocol": "parcel-harness-agent-cycle-v1",
        "status": "prepared",
        "source_campaign_audit": str(args.source_campaign_audit.resolve()),
        "source_campaign_audit_sha256": source_sha,
        "config": str(args.config.resolve()),
        "config_sha256": sha256_file(args.config),
        "failed_runs": len(records),
        "quarantined_candidates": sum(
            record["admission"] is None or not record["admission"]["admitted"]
            for record in records
        ),
        "admitted_positive_corrections": sum(
            bool(record["admission"] and record["admission"]["admitted"])
            for record in records
        ),
        "records": records,
        "claim_boundary": (
            "preparation and evidence admission only; no online control, training, "
            "checkpoint promotion, or registry mutation occurs in this command"
        ),
    }
    payload["cycle_sha256"] = sha256_json(payload)
    _write_json_atomic(args.output, payload)
    print(json.dumps({key: payload[key] for key in (
        "status",
        "failed_runs",
        "quarantined_candidates",
        "admitted_positive_corrections",
        "cycle_sha256",
    )}, indent=2))
    return 0


def _load_replays(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = _read_json(path)
    runs = payload.get("runs")
    if not isinstance(runs, list):
        raise ValueError("replay audit must contain a runs list")
    indexed: dict[str, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("replay audit runs must be objects")
        candidate_id = str(run.get("candidate_id") or "")
        if not candidate_id or candidate_id in indexed:
            raise ValueError("replay audit candidate_id values must be non-empty and unique")
        indexed[candidate_id] = run
    return indexed


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
