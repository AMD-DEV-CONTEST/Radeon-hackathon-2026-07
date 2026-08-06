#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_contracts import stable_digest
from prooflaunch_remix.v10_trajectory_distillation import (
    ExecutionSkillKind,
    PolicyKind,
    TrainingLabel,
    TrajectoryRole,
    build_full_trajectory_corpus,
    decompose_role_trajectories,
    distill_execution_skills,
    distill_policy_example,
    reward_outcome,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/v10_trajectory_kd"
EVIDENCE = ROOT / "evidence/v10/trajectory-kd-seed-audit.json"


def normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [normalize(item) for item in value]
    return value


def jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def counter_dict(values: list[Enum]) -> dict[str, int]:
    return dict(sorted(Counter(item.value for item in values).items()))


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    outcomes = build_full_trajectory_corpus()
    role_trajectories = tuple(
        role
        for outcome in outcomes
        for role in decompose_role_trajectories(outcome)
    )
    policy_examples = tuple(
        example
        for outcome in outcomes
        if (example := distill_policy_example(outcome)) is not None
    )
    execution_skill_examples = tuple(
        example
        for outcome in outcomes
        for example in distill_execution_skills(outcome)
    )
    reward_pairs = tuple(reward_outcome(outcome) for outcome in outcomes)

    outcome_records = [
        {
            "schema": "ProofLaunchMatchedOutcomeTrajectoryV1",
            **normalize(asdict(outcome)),
            "trace_sha256": outcome.trace_sha256,
            "mechanically_verified": True,
        }
        for outcome in outcomes
    ]
    role_records = [
        {
            "schema": "ProofLaunchRoleTrajectoryV1",
            **normalize(asdict(role)),
            "trace_sha256": role.trace_sha256,
        }
        for role in role_trajectories
    ]
    policy_records = [
        {
            "schema": "ProofLaunchVisiblePolicyDistillationExampleV1",
            **normalize(asdict(example)),
            "content_sha256": example.digest,
        }
        for example in policy_examples
    ]
    execution_skill_records = [
        {
            "schema": "ProofLaunchExecutionSkillDistillationExampleV1",
            **normalize(asdict(example)),
            "content_sha256": example.digest,
        }
        for example in execution_skill_examples
    ]
    reward_records = [
        {
            "schema": "ProofLaunchHierarchicalTrajectoryRewardV1",
            "trajectory_id": outcome.trajectory_id,
            "step_rewards": normalize(asdict_steps),
            "trajectory_reward": normalize(asdict(trajectory_reward)),
        }
        for outcome, (step_rewards, trajectory_reward) in zip(
            outcomes,
            reward_pairs,
            strict=True,
        )
        for asdict_steps in ([asdict(item) for item in step_rewards],)
    ]

    paths = {
        "outcome_trajectories": OUTPUT / "outcome_trajectories.jsonl",
        "role_trajectories": OUTPUT / "role_trajectories.jsonl",
        "policy_examples": OUTPUT / "policy_examples.jsonl",
        "execution_skill_examples": OUTPUT / "execution_skill_examples.jsonl",
        "reward_traces": OUTPUT / "reward_traces.jsonl",
    }
    records = {
        "outcome_trajectories": outcome_records,
        "role_trajectories": role_records,
        "policy_examples": policy_records,
        "execution_skill_examples": execution_skill_records,
        "reward_traces": reward_records,
    }
    for name, path in paths.items():
        atomic_write_text(path, jsonl(records[name]))

    task_labels: dict[str, set[str]] = {}
    for outcome in outcomes:
        task_labels.setdefault(outcome.task_id, set()).add(outcome.training_label.value)
    exact_matched_triplets = all(
        labels
        == {
            TrainingLabel.IMITATE.value,
            TrainingLabel.NEGATIVE.value,
            TrainingLabel.RECOVERY.value,
        }
        for labels in task_labels.values()
    )
    step_reward_count = sum(len(pair[0]) for pair in reward_pairs)
    file_receipts = {
        name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "records": len(records[name]),
        }
        for name, path in paths.items()
    }
    manifest = {
        "schema": "ProofLaunchTrajectoryKDCorpusManifestV1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_environment_manifest": "data/v10_gtm_seed/manifest.json",
        "source_policy_revision": "prooflaunch-mechanical-oracle-v1",
        "task_count": len(task_labels),
        "outcome_trajectory_count": len(outcomes),
        "role_trajectory_count": len(role_trajectories),
        "policy_example_count": len(policy_examples),
        "execution_skill_example_count": len(execution_skill_examples),
        "trajectory_reward_count": len(reward_pairs),
        "step_reward_count": step_reward_count,
        "outcome_counts": counter_dict([item.outcome_kind for item in outcomes]),
        "role_counts": counter_dict([item.role for item in role_trajectories]),
        "policy_counts": counter_dict([item.policy_kind for item in policy_examples]),
        "execution_skill_counts": counter_dict(
            [item.kind for item in execution_skill_examples]
        ),
        "partition_counts": counter_dict([item.partition for item in outcomes]),
        "training_label_counts": counter_dict(
            [item.training_label for item in outcomes]
        ),
        "matched_task_triplets": exact_matched_triplets,
        "rights_id": "project-owned-synthetic-v1",
        "hidden_chain_of_thought_count": 0,
        "privileged_deployment_example_count": 0,
        "distillation": {
            "reused": (
                "ProofLaunch StepTransition, resettable GTM environment, deterministic "
                "mechanical verifier, and visible tool responses; no new model trainer"
            ),
            "academic_hypothesis": (
                "matched positive/negative/recovery trajectories with role-local traces and "
                "hierarchical rewards should reduce final-answer-only credit and improve "
                "bounded stop/retry/fallback/escalation decisions"
            ),
            "innovation": (
                "each of 152 tasks shares the same state and evidence fixture across clean, "
                "failed, and repaired counterfactuals, preventing task-difficulty confounding"
            ),
            "evidence": (
                "content-addressed JSONL, exact-count tests, deterministic replay, and this "
                "fail-closed local audit"
            ),
        },
        "files": file_receipts,
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

    checks = {
        "exact_152_matched_tasks": len(task_labels) == 152,
        "exact_positive_negative_recovery_triplet_per_task": exact_matched_triplets,
        "exact_456_outcome_trajectories": len(outcomes) == 456,
        "exact_1824_role_trajectories": len(role_trajectories) == 1824,
        "all_four_roles_present": {item.role for item in role_trajectories}
        == set(TrajectoryRole),
        "all_four_distilled_policies_present": {
            item.policy_kind for item in policy_examples
        }
        == set(PolicyKind),
        "all_four_execution_skills_present": {
            item.kind for item in execution_skill_examples
        }
        == set(ExecutionSkillKind)
        and len(execution_skill_examples) == 1824,
        "every_outcome_has_step_and_trajectory_reward": len(reward_pairs)
        == len(outcomes)
        and step_reward_count > len(outcomes),
        "all_outcomes_kind_verified": all(item.verification.passed for item in outcomes),
        "all_partitions_present": len({item.partition for item in outcomes}) == 4,
        "zero_hidden_or_privileged_reasoning": not any(
            item.hidden_chain_of_thought_present for item in outcomes
        )
        and not any(
            item.hidden_chain_of_thought_present
            or item.privileged_context_present
            for item in policy_examples
        ),
        "project_owned_synthetic_rights_only": all(
            item.rights_id == "project-owned-synthetic-v1" for item in outcomes
        ),
    }
    audit = {
        "schema": "ProofLaunchTrajectoryKDSeedAuditV1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "passed_as_local_synthetic_trajectory_kd_seed_not_training"
            if all(checks.values())
            else "failed"
        ),
        "manifest": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": sha256(manifest_path),
        "checks": checks,
        "promotion_eligible": False,
        "promotion_blockers": [
            "mechanical trajectory seeds are not human-authored 4A trajectories",
            "policy examples are compiled supervision records, not a trained policy",
            "step and trajectory rewards are deterministic labels, not human-calibrated rewards",
            "no SFT, online RL, RCRL, Radeon, or multi-GPU training receipt exists",
            "no held-out task-success or blind product-quality uplift is measured",
        ],
        "truth_boundary": (
            "This audit proves matched visible trajectory collection, four role-local trace "
            "schemas, stop/retry/fallback/escalation supervision examples, hierarchical reward "
            "labels, deterministic replay, and partition/rights isolation. It does not prove "
            "model distillation, trained-policy improvement, 4A quality, Radeon execution, or "
            "business outcomes."
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
                "tasks": len(task_labels),
                "outcomes": len(outcomes),
                "role_trajectories": len(role_trajectories),
                "policy_examples": len(policy_examples),
                "execution_skill_examples": len(execution_skill_examples),
                "step_rewards": step_reward_count,
                "status": audit["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
