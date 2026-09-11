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

from parcel_sorter.confirmation_evidence_audit import audit_confirmation_evidence
from parcel_sorter.grasp_scoring import canonical_payload_sha256, sha256_file


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected TOML object: {path}")
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    protocol = _load_toml(args.protocol)
    manifest = _load_json(args.manifest)
    dataset = _load_json(args.dataset)
    result = _load_json(args.result)
    audit = audit_confirmation_evidence(protocol, manifest, dataset, result)
    hash_errors = []
    for label, path, expected in (
        ("protocol", args.protocol, result.get("protocol_sha256")),
        ("manifest", args.manifest, result.get("manifest_sha256")),
        ("dataset", args.dataset, result.get("dataset_sha256")),
    ):
        actual = sha256_file(path)
        if actual != str(expected):
            hash_errors.append(f"{label}_hash_mismatch")
        audit[f"{label}_sha256"] = actual
    if str(manifest.get("protocol_sha256")) != audit["protocol_sha256"]:
        hash_errors.append("manifest_protocol_hash_mismatch")
    dataset_payload = dict(dataset)
    declared_dataset_payload_hash = str(dataset_payload.pop("dataset_sha256", ""))
    if declared_dataset_payload_hash != canonical_payload_sha256(dataset_payload):
        hash_errors.append("dataset_payload_hash_mismatch")
    if Path(str(manifest.get("protocol", ""))).resolve() != args.protocol.resolve():
        hash_errors.append("manifest_protocol_path_mismatch")
    if Path(str(result.get("protocol", ""))).resolve() != args.protocol.resolve():
        hash_errors.append("result_protocol_path_mismatch")
    if Path(str(result.get("manifest", ""))).resolve() != args.manifest.resolve():
        hash_errors.append("result_manifest_path_mismatch")
    if Path(str(result.get("dataset", ""))).resolve() != args.dataset.resolve():
        hash_errors.append("result_dataset_path_mismatch")
    if hash_errors:
        audit["errors"] = list(dict.fromkeys([*audit["errors"], *hash_errors]))
        audit["status"] = "evidence_invalid"
    audit.update(
        {
            "protocol": str(args.protocol.resolve()),
            "manifest": str(args.manifest.resolve()),
            "dataset": str(args.dataset.resolve()),
            "result": str(args.result.resolve()),
            "result_sha256": sha256_file(args.result),
        }
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit a completed V5 confirmation evidence chain without re-selection."
    )
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": audit["status"], "errors": audit["errors"]}))
    return 0 if audit["status"] == "evidence_valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
