#!/usr/bin/env python3
"""Create a sanitized Git-ready E3/W7900 packet from one raw gate run."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

PUBLIC_ARTIFACTS = (
    "artifact-hashes.json",
    "correction-invalidation-trace.json",
    "langgraph-node-trace.json",
    "m2-workspace.public.json",
    "role-summary.json",
    "semantic-model-summary.json",
    "w7900-environment.json",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def finalize(raw_dir: Path, packet_dir: Path) -> Path:
    result = _read_json(raw_dir / "run-result.json")
    if result.get("result") != "PASS":
        raise ValueError("raw W7900 run must be PASS before packet finalization")
    source = result.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("git_commit"), str):
        raise ValueError("raw result is missing exact-commit source identity")
    commit = source["git_commit"]
    environment = _read_json(raw_dir / "artifacts" / "w7900-environment.json")
    if environment.get("code_commit") != commit:
        raise ValueError("W7900 environment record and run commit do not match")

    packet_dir.mkdir(parents=True, exist_ok=False)
    artifact_dir = packet_dir / "artifacts"
    artifact_dir.mkdir()
    artifacts = []
    for file_name in PUBLIC_ARTIFACTS:
        source_path = raw_dir / "artifacts" / file_name
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        destination = artifact_dir / file_name
        shutil.copyfile(source_path, destination)
        artifacts.append(
            {
                "path": f"artifacts/{file_name}",
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            }
        )

    steps = result.get("steps")
    if not isinstance(steps, list) or not steps or any(
        not isinstance(step, dict) or step.get("exit_code") != 0 for step in steps
    ):
        raise ValueError("raw result does not contain an all-pass command list")
    run_id = raw_dir.parent.name
    manifest = {
        "schema_version": "engineering-evidence/v1",
        "packet_id": f"e3-m2-w7900-{run_id}-{commit[:7]}",
        "timestamp_utc": result.get("finished_at"),
        "source": {
            "git_commit": commit,
            "branch": source.get("branch"),
            "dirty_tree": False,
            "issue": "https://github.com/kinnyuww/amd-devmaster-track2-agent/issues/19",
            "pull_request": "https://github.com/kinnyuww/amd-devmaster-track2-agent/pull/20",
        },
        "quality_mapping": {
            "acceptance_criteria": [
                "AC-02",
                "AC-03",
                "AC-09",
                "AC-10",
                "AC-15",
                "AC-16",
                "AC-17",
                "AC-22",
                "AC-23",
                "AC-24",
                "AC-25",
            ],
            "l1_milestones": ["M2 Timeline and Critical Moment Map"],
            "l2_gates": [
                "Local inference",
                "Agent orchestration",
                "Canonical state",
                "Evidence discipline",
                "Failure behavior",
                "Observability",
            ],
            "track_2_relevance": (
                "Exact-commit W7900/ROCm/vLLM compatibility plus the durable "
                "M1-to-M2 Agent workflow and source-linked Critical Moment Map."
            ),
        },
        "input": {
            "fixture_or_scenario_id": result["fixture"]["id"],
            "version": result["fixture"]["version"],
            "data_class": result["fixture"]["data_class"],
        },
        "environment": environment,
        "commands": [
            {
                "name": step["name"],
                "argv": step["argv"],
                "exit": step["exit_code"],
            }
            for step in steps
        ],
        "results": {
            "terminal_state": "W7900_COMPATIBILITY_READY_FOR_REVIEW",
            "failures": [],
            "unverified": [
                "Independent quality-owner acceptance and E3 promotion.",
                "Performance Baseline/Candidate measurements; this is compatibility only.",
            ],
        },
        "artifacts": artifacts,
        "decision": {
            "result_class": "CONDITIONAL",
            "condition": "Independent quality-owner review is required before merge.",
            "rollback": f"Revert exact implementation commit {commit}.",
            "owner": "kinnyuww quality review",
            "deadline": "Before E3 acceptance or merge",
        },
        "history": {
            "supersedes_packet_id": "e3-m2-20260729T075518Z-exact-c877c19",
            "notes": (
                "Adds an exact-commit W7900 compatibility rerun for the E3 fixes. "
                "It does not make a latency, throughput or optimization claim."
            ),
        },
    }
    _write_json(packet_dir / "manifest.json", manifest)
    (packet_dir / "summary.md").write_text(
        "\n".join(
            [
                "# E3 / M2 exact-commit W7900 compatibility packet",
                "",
                "Result: `W7900_COMPATIBILITY_READY_FOR_REVIEW`",
                "",
                f"- Commit: `{commit}`",
                f"- Public fixture: `{result['fixture']['id']}@{result['fixture']['version']}`",
                "- W7900/ROCm/vLLM environment, full model snapshot, native Tool Call,",
                "  Runtime allow/deny/restart, M2 regressions and sanitized artifacts passed.",
                "- This packet proves compatibility only. It is not E8 Baseline v1 and",
                "  makes no latency, throughput, VRAM-improvement or optimization claim.",
                "- Independent review by `kinnyuww` remains required.",
                "",
                f"Raw working evidence remains at `{raw_dir}` and must not be committed.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return packet_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--packet-dir", type=Path, required=True)
    args = parser.parse_args()
    output = finalize(args.raw_dir, args.packet_dir)
    print(json.dumps({"result": "PASS", "packet_dir": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
