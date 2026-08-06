from __future__ import annotations

import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_curriculum_evaluation import (
    CurriculumArm,
    CurriculumOutcome,
    VerifierIdentity,
    audit_critic_independence,
    build_evolution_report,
    evaluate_paired_curriculum,
)


def verifier(index: int) -> VerifierIdentity:
    return VerifierIdentity(
        verifier_id=f"verifier-{index}",
        principal_id=f"principal-{index}",
        model_family=f"family-{index}",
        checkpoint_revision=f"checkpoint-{index}",
        rubric_sha256="a" * 64,
        prompt_sha256=str(index) * 64,
    )


def outcome(
    pair: int,
    arm: CurriculumArm,
    *,
    success: bool,
    score: float,
    steps: int,
) -> CurriculumOutcome:
    return CurriculumOutcome(
        pair_id=f"pair-{pair}",
        arm=arm,
        task_id=f"task-{pair}",
        environment_revision=f"env-{pair}",
        task_seed=pair,
        checkpoint_revision="checkpoint-frozen",
        success=success,
        verifier_score=score,
        steps=steps,
    )


class CriticIndependenceTests(unittest.TestCase):
    def test_two_blinded_lineage_independent_critics_with_replay_pass(self) -> None:
        receipt = audit_critic_independence(
            producer_principal_id="producer",
            producer_model_family="producer-family",
            producer_checkpoint_revision="producer-checkpoint",
            verifiers=(verifier(1), verifier(2)),
            candidate_ids_blinded=True,
            independent_tool_replay=True,
        )
        self.assertTrue(receipt.passed)
        self.assertEqual(receipt.collusion_blockers, ())
        self.assertEqual(len(receipt.digest), 64)

    def test_self_judging_shared_checkpoint_prompt_or_unblinded_candidate_blocks(self) -> None:
        shared = verifier(1)
        receipt = audit_critic_independence(
            producer_principal_id=shared.principal_id,
            producer_model_family=shared.model_family,
            producer_checkpoint_revision=shared.checkpoint_revision,
            verifiers=(shared, shared),
            candidate_ids_blinded=False,
            independent_tool_replay=False,
        )
        self.assertFalse(receipt.passed)
        self.assertIn("producer principal also acts as verifier", receipt.collusion_blockers)
        self.assertIn("candidate identity is not blinded", receipt.collusion_blockers)
        self.assertIn("no independent tool replay", receipt.collusion_blockers)


class CurriculumEffectTests(unittest.TestCase):
    def test_failure_driven_curriculum_is_paired_against_static_data(self) -> None:
        outcomes = []
        for index in range(12):
            outcomes.extend(
                (
                    outcome(index, CurriculumArm.FAILURE_DRIVEN, success=True, score=0.9, steps=4),
                    outcome(index, CurriculumArm.STATIC, success=index < 6, score=0.7, steps=6),
                )
            )
        effect = evaluate_paired_curriculum(outcomes)
        self.assertEqual(effect.matched_pairs, 12)
        self.assertEqual(effect.failure_driven_success_rate, 1.0)
        self.assertEqual(effect.static_success_rate, 0.5)
        self.assertEqual(effect.success_rate_difference, 0.5)
        self.assertEqual(effect.discordant_wins, 6)
        self.assertEqual(effect.discordant_losses, 0)
        self.assertEqual(effect.mean_step_difference, -2.0)

    def test_evolution_report_stays_unpromoted_for_controlled_nonmodel_fixture(self) -> None:
        with self.assertRaisesRegex(V10ContractError, "unmatched experimental pair"):
            evaluate_paired_curriculum(
                (
                    outcome(1, CurriculumArm.FAILURE_DRIVEN, success=True, score=1.0, steps=2),
                    CurriculumOutcome(
                        **{
                            **outcome(1, CurriculumArm.STATIC, success=False, score=0.5, steps=4).__dict__,
                            "task_seed": 99,
                        }
                    ),
                )
            )
        effect = evaluate_paired_curriculum(
            (
                outcome(1, CurriculumArm.FAILURE_DRIVEN, success=True, score=0.9, steps=2),
                outcome(1, CurriculumArm.STATIC, success=False, score=0.6, steps=4),
            )
        )
        critic = audit_critic_independence(
            producer_principal_id="producer",
            producer_model_family="producer-family",
            producer_checkpoint_revision="producer-checkpoint",
            verifiers=(verifier(1), verifier(2)),
            candidate_ids_blinded=True,
            independent_tool_replay=True,
        )
        report = build_evolution_report(
            effect,
            critic,
            observed_model_inference=False,
            external_held_out=False,
        )
        self.assertFalse(report["promotion_eligible"])
        self.assertIn("no observed model inference", report["promotion_failures"])
        self.assertIn("comparison is not external held-out", report["promotion_failures"])
        self.assertIn("insufficient matched pairs", report["promotion_failures"])
        self.assertEqual(len(report["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
