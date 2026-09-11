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

from parcel_sorter.config import load_config
from parcel_sorter.cylinder_candidate_audit import (
    audit_cylinder_candidate_population,
)
from parcel_sorter.grasp_scoring import sha256_file


PROTOCOL_ID = "cylinder-candidate-population-audit-v1"


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected TOML table: {path}")
    return payload


def audit_protocol(protocol_path: Path) -> dict[str, Any]:
    protocol = _load_toml(protocol_path)
    errors = []
    if str(protocol["metadata"]["protocol_id"]) != PROTOCOL_ID:
        errors.append("protocol_id")
    implementation = protocol["implementation"]
    for name in ("planner", "audit_module", "runner", "catalog"):
        path = PROJECT_ROOT / str(implementation[name])
        expected = str(implementation[f"{name}_sha256"])
        if expected == "PENDING_AFTER_FREEZE":
            errors.append(f"{name}_hash_not_frozen")
        elif sha256_file(path) != expected:
            errors.append(f"{name}_hash_mismatch")
    if errors:
        return {
            "schema_version": "1.0",
            "status": "candidate_population_invalid",
            "protocol_id": str(protocol["metadata"]["protocol_id"]),
            "protocol_sha256": sha256_file(protocol_path),
            "errors": errors,
        }

    catalog_path = PROJECT_ROOT / str(implementation["catalog"])
    config = load_config(catalog_path)
    result = audit_cylinder_candidate_population(config, protocol)
    result.update(
        {
            "protocol": str(protocol_path.resolve()),
            "protocol_sha256": sha256_file(protocol_path),
            "implementation_sha256": {
                name: str(implementation[f"{name}_sha256"])
                for name in ("planner", "audit_module", "runner", "catalog")
            },
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_protocol(args.protocol)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "observed_samples": result.get("observed_samples", 0),
                "errors": result["errors"],
            }
        )
    )
    return 0 if result["status"] == "candidate_population_valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
