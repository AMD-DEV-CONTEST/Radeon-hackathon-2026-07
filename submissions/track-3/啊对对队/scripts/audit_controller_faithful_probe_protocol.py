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

from parcel_sorter.controller_faithful_probe import PROBE_POLICIES, PROBE_FEATURE_NAMES
from parcel_sorter.grasp_scoring import sha256_file


def audit_protocol(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    metadata = payload["metadata"]
    source = payload["source"]
    implementation = payload["implementation"]
    fixed = payload["fixed"]
    errors: list[str] = []
    if str(metadata["protocol_id"]) != "controller-faithful-probe-v4-train-only":
        errors.append("protocol_id")
    if not bool(source["development_forbidden"]):
        errors.append("development_not_forbidden")
    if not bool(source["holdout_forbidden"]):
        errors.append("holdout_not_forbidden")
    observed_policies = tuple(str(value) for value in fixed["policies"])
    if observed_policies != PROBE_POLICIES:
        errors.append("policy_grid_changed")
    if len(PROBE_FEATURE_NAMES) != 27:
        errors.append("feature_schema_changed")
    for key in ("module", "runner", "audit"):
        declared = str(implementation[f"{key}_sha256"])
        if declared == "PENDING_AFTER_FREEZE":
            errors.append(f"{key}_hash_not_frozen")
        else:
            actual_path = PROJECT_ROOT / str(implementation[key])
            if sha256_file(actual_path) != declared:
                errors.append(f"{key}_hash_mismatch")
    return {
        "schema_version": "1.0",
        "status": "protocol_valid" if not errors else "protocol_invalid",
        "protocol": str(path.resolve()),
        "protocol_sha256": sha256_file(path),
        "protocol_id": str(metadata["protocol_id"]),
        "feature_count": len(PROBE_FEATURE_NAMES),
        "policy_names": list(observed_policies),
        "development_forbidden": bool(source["development_forbidden"]),
        "holdout_forbidden": bool(source["holdout_forbidden"]),
        "manifest_observed": Path(str(source["manifest"])).is_file(),
        "manifest_sha256_declared": str(source["manifest_sha256"]),
        "implementation_hashes": {
            "module": str(implementation["module_sha256"]),
            "runner": str(implementation["runner_sha256"]),
            "audit": str(implementation["audit_sha256"]),
        },
        "errors": errors,
    }


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
    print(json.dumps({"status": result["status"], "errors": result["errors"]}))
    return 0 if result["status"] == "protocol_valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
