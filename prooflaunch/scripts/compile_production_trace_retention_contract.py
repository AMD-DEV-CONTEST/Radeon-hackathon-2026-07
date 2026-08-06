#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.production_trace_ledger import (
    POLICY_VERSION,
    ProductionTraceLedger,
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile the local production request-trace retention proof."
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/production-trace-retention-v1.json"),
    )
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()

    with tempfile.TemporaryDirectory() as temporary:
        ledger = ProductionTraceLedger(
            Path(temporary).resolve() / "production-traces",
            retention_days=90,
        )
        ledger.append(
            method="POST",
            route="/v1/runs",
            status_code=202,
            duration_ms=8.75,
            request_bytes=512,
            response_bytes=128,
            tenant_id="synthetic-local-retention-proof",
            trace_id="synthetic-local-retention-proof-trace-0001",
            exception_observed=False,
        )
        restarted = ProductionTraceLedger(ledger.root, retention_days=90)
        status = restarted.status(tenant_id="synthetic-local-retention-proof")

    source_paths = (
        "src/prooflaunch_remix/production_trace_ledger.py",
        "src/prooflaunch_remix/v10_submission_production_api.py",
        "tests/test_production_trace_ledger.py",
        "tests/test_v10_submission_production_api.py",
        ".github/workflows/quality.yml",
    )
    payload: dict[str, Any] = {
        "schema": "ProofLaunchProductionTraceRetentionContractV1",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "policy_version": POLICY_VERSION,
        "retention_days": status["retention_days"],
        "local_restart_smoke_observed": True,
        "local_request_trace_count": status["request_trace_count"],
        "hash_chain_valid": status["hash_chain_valid"],
        "valid_request_boundary_instrumented": status[
            "valid_request_boundary_instrumented"
        ],
        "raw_content_retained": status["raw_content_retained"],
        "ci_artifact_retention_days": 30,
        "source_file_sha256": {
            relative: _file_digest(ROOT / relative) for relative in source_paths
        },
        "remote_required_check_observed": False,
        "production_deployment_observed": False,
        "production_trace_coverage_observed": False,
        "truth_boundary": (
            "This receipt proves a local restart-durable, content-free, hash-chained "
            "request-trace smoke run and a 90-day runtime retention contract. It does "
            "not prove a protected remote required check, deployed traffic coverage, "
            "incident recovery, production reliability, user effect, lift or revenue."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "retention_days": payload["retention_days"],
                "hash_chain_valid": payload["hash_chain_valid"],
                "content_sha256": payload["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
