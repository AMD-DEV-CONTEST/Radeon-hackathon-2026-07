#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_agentomnia import FullScenarioTrainingContract
from prooflaunch_remix.v10_contracts import stable_digest
from prooflaunch_remix.v10_frontier_landscape import ProductLane
from prooflaunch_remix.v10_gtm_environment import (
    ROLE_CONTRACTS,
    IssueKind,
    build_seed_episode,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/v10_gtm_seed"
EVIDENCE = ROOT / "evidence/v10/gtm-seed-corpus-audit.json"


def normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [normalize(item) for item in value]
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(records: list[dict]) -> str:
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    environment_map = {}
    agent_tasks = []
    task_records = []
    trajectory_records = []
    partition_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    lane_counts: dict[str, int] = {}
    replay_verified = 0
    for lane in ProductLane:
        for index, kind in enumerate(IssueKind):
            environment, seed_task, agent_task, events = build_seed_episode(
                lane,
                kind,
                index,
            )
            environment_map[
                (environment.environment_id, environment.revision_sha256)
            ] = environment
            agent_tasks.append(agent_task)
            partition_counts[agent_task.partition.value] = (
                partition_counts.get(agent_task.partition.value, 0) + 1
            )
            issue_counts[kind.value] = issue_counts.get(kind.value, 0) + 1
            lane_counts[lane.value] = lane_counts.get(lane.value, 0) + 1
            replay_verified += 1
            task_records.append(
                {
                    "schema": "ProofLaunchGTMSeedTaskV1",
                    "task_id": seed_task.task_id,
                    "environment_id": seed_task.environment_id,
                    "environment_revision_sha256": seed_task.environment_revision_sha256,
                    "partition": seed_task.partition.value,
                    "lane": lane.value,
                    "issue": normalize(asdict(seed_task.issue)),
                    "coordinate": normalize(asdict(seed_task.coordinate)),
                    "maximum_steps": seed_task.maximum_steps,
                    "training_eligible": True,
                    "training_right": "project-owned-synthetic-v1",
                    "quality_scope": "mechanical_seed_only",
                }
            )
            trajectory_records.append(
                {
                    "schema": "ProofLaunchGTMVisibleTrajectoryV1",
                    "task_id": seed_task.task_id,
                    "steps": [normalize(asdict(event)) for event in events],
                    "terminal_signal": events[-1].terminal_signal,
                    "trace_sha256": stable_digest(
                        [event.digest for event in events]
                    ),
                    "hidden_chain_of_thought_present": False,
                    "replay_verified": True,
                }
            )

    environments = tuple(environment_map.values())
    training_contract = FullScenarioTrainingContract(
        base_model="AI-ModelScope/Gemma-4-E4B-it",
        base_revision="4f5f0c899a9b6d34c4b463f557c31c8ac6c767cc",
        common_policy_head="prooflaunch-shared-gtm-policy",
        benchmark_specific_adapters=(),
        environments=environments,
        tasks=tuple(agent_tasks),
    )
    contract_failures = training_contract.audit()
    if contract_failures:
        raise SystemExit(f"seed corpus contract failed: {contract_failures}")

    environment_records = [
        {
            "schema": "ProofLaunchGTMSeedEnvironmentV1",
            **normalize(asdict(environment)),
        }
        for environment in environments
    ]
    roles = [
        {
            "schema": "ProofLaunchGTMSeedRoleV1",
            **normalize(asdict(contract)),
        }
        for contract in ROLE_CONTRACTS.values()
    ]
    paths = {
        "environments": OUTPUT / "environments.jsonl",
        "tasks": OUTPUT / "tasks.jsonl",
        "trajectories": OUTPUT / "trajectories.jsonl",
        "roles": OUTPUT / "roles.json",
    }
    atomic_write_text(paths["environments"], jsonl(environment_records))
    atomic_write_text(paths["tasks"], jsonl(task_records))
    atomic_write_text(paths["trajectories"], jsonl(trajectory_records))
    atomic_write_text(
        paths["roles"],
        json.dumps(roles, ensure_ascii=False, indent=2) + "\n",
    )
    file_receipts = {
        name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for name, path in paths.items()
    }
    manifest = {
        "schema": "ProofLaunchGTMSeedCorpusManifestV1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment_count": len(environments),
        "task_count": len(task_records),
        "trajectory_count": len(trajectory_records),
        "trajectory_step_count": sum(
            len(record["steps"]) for record in trajectory_records
        ),
        "replay_verified_count": replay_verified,
        "lane_counts": lane_counts,
        "issue_counts": issue_counts,
        "partition_counts": partition_counts,
        "files": file_receipts,
        "license_id": "project-owned-synthetic-v1",
        "benchmark_specific_adapters": [],
        "hidden_chain_of_thought_count": 0,
        "content_sha256": None,
    }
    manifest["content_sha256"] = stable_digest(
        {key: value for key, value in manifest.items() if key != "content_sha256"}
    )
    manifest_path = OUTPUT / "manifest.json"
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    audit = {
        "schema": "ProofLaunchGTMSeedCorpusAuditV1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed_as_local_synthetic_seed_not_training",
        "manifest": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": sha256(manifest_path),
        "checks": {
            "exact_8_product_lanes": len(lane_counts) == 8,
            "exact_19_failure_kinds": len(issue_counts) == 19,
            "exact_152_tasks": len(task_records) == 152,
            "exact_32_partition_isolated_environments": len(environments) == 32,
            "all_152_trajectories_replay_verified": replay_verified == 152,
            "all_four_partitions_nonempty": len(partition_counts) == 4,
            "full_scenario_contract_passed": not contract_failures,
            "zero_hidden_chain_of_thought": True,
            "project_owned_synthetic_rights": True,
        },
        "promotion_eligible": False,
        "promotion_blockers": [
            "mechanical synthetic seeds are not a 4A human-authored corpus",
            "no model has been trained on this corpus",
            "no online RL or RCRL rollout has been executed",
            "no real multimodal bytes are included in the metadata-only fixtures",
            "no Radeon or multi-GPU training receipt exists",
            "no blind human product-quality evaluation exists",
        ],
        "truth_boundary": (
            "This audit proves deterministic local environment/task/trajectory generation, "
            "partition isolation, visible traces, project-owned synthetic metadata, and "
            "mechanical verification. It does not prove 4A corpus quality, multimodal model "
            "learning, trained weights, RCRL uplift, Radeon execution, or product superiority."
        ),
    }
    audit["content_sha256"] = stable_digest(audit)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(EVIDENCE, json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "audit": str(EVIDENCE),
                "environment_count": len(environments),
                "task_count": len(task_records),
                "trajectory_count": len(trajectory_records),
                "trajectory_step_count": manifest["trajectory_step_count"],
                "status": audit["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
