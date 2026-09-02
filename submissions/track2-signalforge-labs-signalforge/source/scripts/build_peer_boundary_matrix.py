#!/usr/bin/env python3
"""Build a value-free peer-comparison boundary matrix from governed receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "signalforge/technology20-peer-boundary-matrix/v1"


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def operand_boundary(operand: dict[str, Any]) -> dict[str, Any]:
    return {
        "company_id": operand["company_id"],
        "security_id": operand["security_id"],
        "security_class_state": "not_activated",
        "definition_id": operand["definition_id"],
        "taxonomy_concept": operand["taxonomy_concept"],
        "unit": operand["unit"],
        "currency": operand.get("currency", "not_applicable"),
        "scale": operand["scale"],
        "sign_policy": operand["sign_policy"],
        "dimensional_identity": operand["dimensional_identity"],
        "segment_scope": (
            "consolidated"
            if operand["dimensional_identity"] == "consolidated"
            else "not_comparable"
        ),
        "accounting_perimeter": operand["accounting_perimeter"],
        "period_type": operand["period_type"],
        "fiscal_start": operand["fiscal_start"],
        "fiscal_end": operand["fiscal_end"],
        "filing_date": operand["filing_date"],
        "market_observation_state": "not_activated",
        "market_observation_date": None,
    }


def build_matrix(source: dict[str, Any], source_sha256: str) -> dict[str, Any]:
    lanes: list[dict[str, Any]] = []
    for lane in sorted(source["lanes"], key=lambda item: item["lane_id"]):
        metrics: list[dict[str, Any]] = []
        for receipt in sorted(
            lane.get("receipts", []),
            key=lambda item: item["operands"][0]["canonical_metric_id"],
        ):
            metrics.append(
                {
                    "metric_id": receipt["operands"][0]["canonical_metric_id"],
                    "disposition": receipt["disposition"],
                    "operands": [
                        operand_boundary(operand)
                        for operand in sorted(
                            receipt["operands"], key=lambda item: item["company_id"]
                        )
                    ],
                    "invariants": receipt["invariants"],
                    "required_caveat_ids": receipt.get("required_caveat_ids", []),
                    "receipt_id": receipt["receipt_id"],
                    "receipt_sha256": receipt["receipt_sha256"],
                }
            )
        for abstention in sorted(
            lane.get("abstentions", []),
            key=lambda item: item["metric_ids"][0],
        ):
            metrics.append(
                {
                    "metric_id": abstention["metric_ids"][0],
                    "disposition": "unavailable",
                    "operands": [],
                    "invariants": [],
                    "required_caveat_ids": [abstention["code"]],
                    "abstention_id": abstention["abstention_id"],
                }
            )
        lanes.append(
            {
                "lane_id": lane["lane_id"],
                "company_ids": sorted(lane["company_ids"]),
                "promoted": lane["promoted"],
                "metrics": sorted(metrics, key=lambda item: item["metric_id"]),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "universe_id": source["universe_id"],
        "as_of": source["as_of"],
        "policy_version": source["policy_version"],
        "source_sha256": source_sha256,
        "lanes": lanes,
        "claim_boundary": (
            "This value-free projection exposes comparison boundaries only. It does not "
            "promote a peer lane, authorize a pair-level ranking, activate a market price, "
            "or resolve an unreviewed security class."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_bytes = args.input.read_bytes()
    source = json.loads(source_bytes)
    matrix = build_matrix(source, sha256_bytes(source_bytes))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(matrix))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": sha256_bytes(args.output.read_bytes()),
                "lanes": len(matrix["lanes"]),
                "metrics": sum(len(lane["metrics"]) for lane in matrix["lanes"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
