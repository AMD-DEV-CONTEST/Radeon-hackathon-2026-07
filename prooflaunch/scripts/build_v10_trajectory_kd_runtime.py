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
from prooflaunch_remix.v10_contracts import stable_digest
from prooflaunch_remix.v10_trajectory_distillation import (
    build_full_trajectory_corpus,
)
from prooflaunch_remix.v10_trajectory_kd_runtime import (
    AblationArm,
    LengthBucket,
    TrajectoryRole,
    assign_hierarchical_credit,
    build_information_ablations,
    build_temporal_curriculum,
    build_trajectory_card,
    diagnose_trajectory,
    evaluate_mechanical_pipeline,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/v10_trajectory_kd"
AUDIT = ROOT / "evidence/v10/trajectory-kd-runtime-audit.json"
CARD = ROOT / "evidence/v10/trajectory-card.json"


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


def jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )


def diagnostic_fixtures() -> tuple[object, ...]:
    healthy = diagnose_trajectory(
        "healthy-low-divergence",
        ({"inspect": 0.9, "repair": 0.1},) * 3,
        ({"inspect": 0.85, "repair": 0.15},) * 3,
        (True, True, True),
        (True, True, True),
        ("s0:inspect", "s1:repair", "s2:stop"),
    )
    teacher = (
        {"inspect": 0.99, "repair": 0.01},
        {"inspect": 0.99, "repair": 0.01},
        {"inspect": 0.99, "repair": 0.01},
        {"inspect": 0.99, "repair": 0.01},
    )
    student = (
        {"inspect": 0.99, "repair": 0.01},
        {"inspect": 0.01, "repair": 0.99},
        {"inspect": 0.01, "repair": 0.99},
        {"inspect": 0.01, "repair": 0.99},
    )
    all_faults = diagnose_trajectory(
        "controlled-all-faults",
        teacher,
        student,
        (True, True, True, True),
        (False, False, False, False),
        ("s0:inspect", "s1:repair", "s1:repair", "s1:repair"),
    )
    return healthy, all_faults


def main() -> int:
    source_manifest = DATA / "manifest.json"
    if not source_manifest.is_file():
        raise SystemExit("run build_v10_trajectory_kd_corpus.py first")
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    outcomes = build_full_trajectory_corpus()
    if source.get("outcome_trajectory_count") != len(outcomes):
        raise SystemExit("source manifest and runtime outcome count disagree")

    credits = tuple(assign_hierarchical_credit(item) for item in outcomes)
    curriculum = build_temporal_curriculum(outcomes)
    diagnostics = diagnostic_fixtures()
    ablations = build_information_ablations()
    evaluation = evaluate_mechanical_pipeline(outcomes)
    card = build_trajectory_card(
        outcomes,
        source_manifest_sha256=sha256(source_manifest),
        diagnostic_digests=tuple(item.digest for item in diagnostics),
    )

    credit_path = DATA / "credit_assignments.jsonl"
    curriculum_path = DATA / "temporal_curriculum.json"
    diagnostic_path = DATA / "diagnostic_fixtures.json"
    ablation_path = DATA / "information_ablations.json"
    evaluation_path = DATA / "mechanical_evaluation.json"
    atomic_write_text(
        credit_path,
        jsonl(
            [
                {
                    "schema": "ProofLaunchHierarchicalCreditAssignmentV1",
                    **normalize(asdict(item)),
                    "content_sha256": item.digest,
                }
                for item in credits
            ]
        ),
    )
    atomic_write_text(
        curriculum_path,
        json.dumps(
            {
                "schema": "ProofLaunchTemporalTrajectoryCurriculumV1",
                **normalize(asdict(curriculum)),
                "content_sha256": curriculum.digest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    atomic_write_text(
        diagnostic_path,
        json.dumps(
            [
                {
                    "schema": "ProofLaunchTrajectoryDiagnosticV1",
                    **normalize(asdict(item)),
                    "content_sha256": item.digest,
                }
                for item in diagnostics
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    atomic_write_text(
        ablation_path,
        json.dumps(
            [
                {
                    "schema": "ProofLaunchTrajectoryInformationAblationV1",
                    **normalize(asdict(item)),
                }
                for item in ablations
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    atomic_write_text(
        evaluation_path,
        json.dumps(
            {
                "schema": "ProofLaunchTrajectoryMechanicalEvaluationV1",
                **normalize(asdict(evaluation)),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    CARD.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(CARD, json.dumps(normalize(card), ensure_ascii=False, indent=2) + "\n")

    stage_counts = {
        stage.bucket.value: len(stage.trajectory_ids)
        for stage in curriculum.stages
    }
    diagnostic_flags = {
        flag for item in diagnostics for flag in item.flags
    }
    checks = {
        "exact_456_hierarchical_credit_assignments": len(credits) == 456,
        "every_assignment_has_four_role_credits": all(
            {credit.role for credit in item.role_credits} == set(TrajectoryRole)
            for item in credits
        ),
        "zero_final_only_credit": all(
            item.final_only_credit_blocked and item.nonterminal_credited_steps
            for item in credits
        ),
        "all_upstream_propagation_guards_enabled": all(
            item.upstream_propagation_guarded for item in credits
        ),
        "curriculum_order_is_short_medium_long": [
            stage.bucket for stage in curriculum.stages
        ]
        == [LengthBucket.SHORT, LengthBucket.MEDIUM, LengthBucket.LONG],
        "all_curriculum_stages_nonempty": all(stage_counts.values()),
        "validation_and_evaluation_held_out": {
            item.value for item in curriculum.held_out_partitions
        }
        == {"validation", "evaluation"},
        "diagnostics_cover_kl_compounding_noise_and_loop": diagnostic_flags
        == {
            "trajectory_kl_explosion",
            "compounding_error",
            "tool_noise_regression",
            "invalid_loop",
        },
        "exact_three_ablation_arms": {item.arm for item in ablations}
        == set(AblationArm),
        "held_out_mechanical_evaluation_is_complete": (
            evaluation.held_out_task_count == 24
            and evaluation.outcome_count == 72
            and evaluation.attribution_eligible_count == 48
        ),
        "trained_model_metrics_remain_unclaimed": (
            evaluation.trained_model_attribution_accuracy is None
            and evaluation.trained_model_task_success_rate is None
            and card["trained_model_metrics"] is None
            and not card["promotion_eligible"]
        ),
        "trajectory_card_is_frozen_and_content_addressed": (
            card["frozen"] is True
            and len(str(card["content_sha256"])) == 64
        ),
    }
    evidence_files = {
        path.name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in (
            credit_path,
            curriculum_path,
            diagnostic_path,
            ablation_path,
            evaluation_path,
            CARD,
        )
    }
    audit = {
        "schema": "ProofLaunchTrajectoryKDRuntimeAuditV1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "passed_as_mechanical_runtime_not_model_training"
            if all(checks.values())
            else "failed"
        ),
        "source_manifest": str(source_manifest.relative_to(ROOT)),
        "source_manifest_sha256": sha256(source_manifest),
        "counts": {
            "credit_assignments": len(credits),
            "curriculum_stage_trajectories": stage_counts,
            "diagnostic_fixtures": len(diagnostics),
            "ablation_arms": len(ablations),
            "held_out_evaluation_outcomes": evaluation.outcome_count,
        },
        "checks": checks,
        "files": evidence_files,
        "promotion_eligible": False,
        "promotion_blockers": [
            "credit labels are mechanical and have not been calibrated against human role attribution",
            "KL/noise/loop monitors were validated on controlled fixtures, not model logits or live tools",
            "ablation arms prove information availability only; no model was trained for any arm",
            "held-out metrics are oracle/parser checks, not learned-policy accuracy or task success",
            "no Radeon, multi-GPU, SFT, online RL, RCRL, or independent 4A receipt exists",
        ],
        "truth_boundary": card["truth_boundary"],
    }
    audit["content_sha256"] = stable_digest(audit)
    atomic_write_text(AUDIT, json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "audit": str(AUDIT),
                "card": str(CARD),
                "credit_assignments": len(credits),
                "stage_counts": stage_counts,
                "held_out_outcomes": evaluation.outcome_count,
                "status": audit["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
