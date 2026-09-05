#!/usr/bin/env python3
"""Create a sanitized Git-ready E4/W7900 packet from one raw gate run."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

PUBLIC_ARTIFACTS = (
    "artifact-hashes.json",
    "m3-correction-regeneration-trace.json",
    "m3-forged-permission-contract.json",
    "m3-invalid-output-recovery-trace.json",
    "m3-langgraph-node-trace.json",
    "m3-model-summary.json",
    "m3-policy-denial-trace.json",
    "m3-restart-idempotency-summary.json",
    "m3-role-evidence-summary.json",
    "m3-unsupported-claim-trace.json",
    "m3-workspace.public.json",
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


def _validate_public_artifacts(raw_dir: Path, commit: str) -> dict[str, Any]:
    artifact_dir = raw_dir / "artifacts"
    hashes = _read_json(artifact_dir / "artifact-hashes.json")
    if hashes.get("code_commit") != commit:
        raise ValueError("M3 artifact hash record and run commit do not match")
    expected_hashes = hashes.get("sha256")
    if not isinstance(expected_hashes, dict):
        raise ValueError("M3 artifact hash record is missing its SHA-256 map")
    for file_name in PUBLIC_ARTIFACTS:
        path = artifact_dir / file_name
        if not path.is_file():
            raise FileNotFoundError(path)
        if file_name == "artifact-hashes.json":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_hashes.get(file_name) != digest:
            raise ValueError(f"sanitized artifact hash mismatch: {file_name}")

    model = _read_json(artifact_dir / "m3-model-summary.json")
    runs = model.get("runs")
    if not isinstance(runs, list) or len(runs) < 2:
        raise ValueError("M3 model summary must contain create and regeneration runs")
    for run in runs:
        if (
            not isinstance(run, dict)
            or run.get("code_commit") != commit
            or run.get("terminal_state") != "SUCCEEDED"
            or not run.get("proposal_metadata")
        ):
            raise ValueError("M3 model run is missing exact-commit success metadata")
        for metadata in run["proposal_metadata"]:
            if metadata.get("server_kind") != "vllm":
                raise ValueError("W7900 packet cannot use fake M3 model metadata")
            if not str(metadata.get("server_base_url", "")).startswith(
                ("http://127.0.0.1", "http://localhost", "http://[::1]")
            ):
                raise ValueError("M3 model metadata must retain a loopback endpoint")

    policy = _read_json(artifact_dir / "m3-policy-denial-trace.json")
    if (
        policy.get("tool_execution_effect_count") != 0
        or policy.get("status", {}).get("terminal_state") != "POLICY_BLOCKED"
    ):
        raise ValueError("M3 policy denial must prove a zero-effect terminal")
    unsupported = _read_json(artifact_dir / "m3-unsupported-claim-trace.json")
    if (
        unsupported.get("persisted_m3_artifact") is not False
        or unsupported.get("status", {}).get("terminal_state")
        != "INVALID_MODEL_OUTPUT"
    ):
        raise ValueError("unsupported M3 claim did not fail before persistence")
    return hashes


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
    artifact_hash_record = _validate_public_artifacts(raw_dir, commit)

    steps = result.get("steps")
    if not isinstance(steps, list) or not steps or any(
        not isinstance(step, dict) or step.get("exit_code") != 0 for step in steps
    ):
        raise ValueError("raw result does not contain an all-pass command list")

    packet_dir.mkdir(parents=True, exist_ok=False)
    artifact_dir = packet_dir / "artifacts"
    artifact_dir.mkdir()
    artifacts = []
    for file_name in PUBLIC_ARTIFACTS:
        source_path = raw_dir / "artifacts" / file_name
        destination = artifact_dir / file_name
        shutil.copyfile(source_path, destination)
        artifacts.append(
            {
                "path": f"artifacts/{file_name}",
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            }
        )

    run_id = raw_dir.parent.name
    manifest = {
        "schema_version": "engineering-evidence/v1",
        "packet_id": f"e4-m3-w7900-{run_id}-{commit[:7]}",
        "timestamp_utc": result.get("finished_at"),
        "source": {
            "git_commit": commit,
            "branch": source.get("branch"),
            "dirty_tree": False,
            "issue": (
                "https://github.com/kinnyuww/"
                "amd-devmaster-track2-agent/issues/21"
            ),
            "pull_request": (
                "https://github.com/kinnyuww/"
                "amd-devmaster-track2-agent/pull/22"
            ),
        },
        "quality_mapping": {
            "acceptance_criteria": [
                "AC-02",
                "AC-03",
                "AC-09",
                "AC-10",
                "AC-15",
                "AC-16",
                "AC-18",
                "AC-22",
                "AC-23",
                "AC-24",
                "AC-25",
            ],
            "l1_milestones": ["M3 Decision and Evidence Ledger"],
            "l2_gates": [
                "Local inference",
                "Agent orchestration",
                "Canonical state",
                "Evidence discipline",
                "Runtime permission",
                "Failure behavior",
                "Observability",
            ],
            "track_2_relevance": (
                "Exact-commit W7900/ROCm/vLLM compatibility plus a bounded "
                "M2-to-M3 private Agent workflow, deterministic zero-effect "
                "permission denial, correction regeneration and durable evidence."
            ),
        },
        "input": {
            "fixture_or_scenario_id": result["fixture"]["id"],
            "version": result["fixture"]["version"],
            "data_class": result["fixture"]["data_class"],
            "sha256": artifact_hash_record["fixture_sha256"],
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
                "Independent quality-owner acceptance and E4 promotion.",
                "Browser journey was verified locally, not inside the W7900 gate.",
                (
                    "Performance Baseline/Candidate measurements; this packet "
                    "is compatibility only."
                ),
            ],
        },
        "artifacts": artifacts,
        "decision": {
            "result_class": "CONDITIONAL",
            "condition": "Independent quality-owner review is required before merge.",
            "rollback": f"Revert exact implementation commit {commit}.",
            "owner": "kinnyuww quality review",
            "deadline": "Before E4 acceptance or merge",
        },
        "history": {
            "supersedes_packet_id": None,
            "notes": (
                "Exact-commit E4/M3 W7900 compatibility run. Deterministic "
                "negative-path artifacts are explicitly separate from real-model "
                "create/regeneration evidence. No performance claim is made."
            ),
        },
    }
    _write_json(packet_dir / "manifest.json", manifest)
    (packet_dir / "summary.md").write_text(
        "\n".join(
            [
                "# E4 / M3 exact-commit W7900 compatibility packet",
                "",
                "Result: `W7900_COMPATIBILITY_READY_FOR_REVIEW`",
                "",
                f"- Commit: `{commit}`",
                (
                    f"- Public fixture: `{result['fixture']['id']}@"
                    f"{result['fixture']['version']}`"
                ),
                "- W7900/ROCm/vLLM environment and full model snapshot passed.",
                "- Real localhost model create and correction-regeneration runs passed.",
                "- Explicit review, SQLite restart, bounded repair, unsupported-claim",
                "  rejection, forged permission rejection and zero-effect policy denial passed.",
                "- Raw prompts, model responses, tool arguments and observations are not retained.",
                "- This is compatibility evidence, not E8 performance evidence.",
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
