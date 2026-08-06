#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/cortex_x_v10_reuse_manifest_v1.json"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Secret-free reachability preflight for frozen upstream revisions."
    )
    result.add_argument("--project-id", action="append", default=[])
    result.add_argument(
        "--network-head-check",
        action="store_true",
        help="Observe current HEAD; a drift is reported but never rewrites the frozen revision.",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = payload["projects"]
    if args.project_id:
        requested = set(args.project_id)
        selected = [item for item in selected if item["project_id"] in requested]
        missing = sorted(requested - {item["project_id"] for item in selected})
        if missing:
            raise SystemExit(f"unknown project IDs: {missing}")
    rows = []
    for item in selected:
        row = {
            "project_id": item["project_id"],
            "frozen_revision": item["revision"],
            "license_gate": item["license_approved_for_code_reuse"],
            "rocm_evidence_level": item["rocm_evidence_level"],
            "network_checked": False,
            "reachable": None,
            "current_head": None,
            "head_drifted": None,
            "runtime_smoke": "not_run",
            "rocm_smoke": "not_run",
        }
        if args.network_head_check:
            completed = subprocess.run(
                ["git", "ls-remote", item["repository_url"], "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            current = completed.stdout.split()[0] if completed.returncode == 0 and completed.stdout.split() else None
            row.update(
                {
                    "network_checked": True,
                    "reachable": current is not None,
                    "current_head": current,
                    "head_drifted": current != item["revision"] if current else None,
                }
            )
        rows.append(row)
    print(
        json.dumps(
            {
                "schema": "ProofLaunchUpstreamSmokePreflightV1",
                "manifest_content_sha256": payload["content_sha256"],
                "rows": rows,
                "truth_boundary": (
                    "Repository reachability and HEAD equality are not runtime or ROCm smoke tests. "
                    "This command never changes the frozen revision."
                ),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
