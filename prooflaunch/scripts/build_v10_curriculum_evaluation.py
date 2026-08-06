#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_curriculum_evaluation import (
    CurriculumArm,
    CurriculumOutcome,
    VerifierIdentity,
    audit_critic_independence,
    build_evolution_report,
    evaluate_paired_curriculum,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/v10_curriculum_evaluation"
REPORT = ROOT / "evidence/v10/curriculum-evolution-report.json"


def verifier(index: int) -> VerifierIdentity:
    return VerifierIdentity(
        verifier_id=f"controlled-verifier-{index}",
        principal_id=f"controlled-principal-{index}",
        model_family=f"controlled-family-{index}",
        checkpoint_revision=f"controlled-checkpoint-{index}",
        rubric_sha256="a" * 64,
        prompt_sha256=str(index) * 64,
    )


def main() -> int:
    critic = audit_critic_independence(
        producer_principal_id="controlled-producer-principal",
        producer_model_family="controlled-producer-family",
        producer_checkpoint_revision="controlled-producer-checkpoint",
        verifiers=(verifier(1), verifier(2)),
        candidate_ids_blinded=True,
        independent_tool_replay=True,
    )
    outcomes = []
    for index in range(24):
        common = {
            "pair_id": f"controlled-pair-{index:03d}",
            "task_id": f"controlled-task-{index:03d}",
            "environment_revision": f"controlled-environment-{index:03d}",
            "task_seed": index,
            "checkpoint_revision": "controlled-not-a-model-checkpoint",
        }
        outcomes.extend(
            (
                CurriculumOutcome(
                    **common,
                    arm=CurriculumArm.FAILURE_DRIVEN,
                    success=True,
                    verifier_score=0.90,
                    steps=4,
                ),
                CurriculumOutcome(
                    **common,
                    arm=CurriculumArm.STATIC,
                    success=index < 12,
                    verifier_score=0.70,
                    steps=6,
                ),
            )
        )
    effect = evaluate_paired_curriculum(outcomes)
    report = build_evolution_report(
        effect,
        critic,
        observed_model_inference=False,
        external_held_out=False,
        minimum_pairs=100,
    )
    report.update(
        {
            "status": "passed_as_controlled_mechanical_comparison_not_curriculum_uplift",
            "critic_independence": asdict(critic),
            "outcome_count": len(outcomes),
            "fixture_kind": "project_owned_controlled_nonmodel",
            "curriculum_engine_v1_frozen": True,
            "trained_curriculum_effect_claimed": False,
        }
    )
    report["content_sha256"] = stable_sha256(
        {key: value for key, value in report.items() if key != "content_sha256"}
    )
    DATA.mkdir(parents=True, exist_ok=True)
    outcomes_path = DATA / "paired-outcomes.jsonl"
    atomic_write_text(
        outcomes_path,
        "".join(
            json.dumps(
                {**asdict(item), "arm": item.arm.value},
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for item in outcomes
        ),
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(REPORT, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not critic.passed or report["promotion_eligible"]:
        raise SystemExit("curriculum evaluation truth boundary failed")
    print(
        json.dumps(
            {
                "status": report["status"],
                "matched_pairs": effect.matched_pairs,
                "mechanical_difference": effect.success_rate_difference,
                "promotion_eligible": report["promotion_eligible"],
                "report": str(REPORT.relative_to(ROOT)),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
