from __future__ import annotations

import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_sft_contract import (
    CANONICAL_INPUT_ORDER,
    CANONICAL_STAGE_ORDER,
    ComparisonMetric,
    CurriculumStage,
    SFTContract,
    StageArtifact,
    StageReplay,
    TrainerVariant,
    build_controlled_replay,
    default_input_curriculum,
    default_loss_policy,
    default_stage_definitions,
    default_trainer_contracts,
    planned_sft_card,
)


def contract() -> SFTContract:
    return SFTContract(
        stages=default_stage_definitions(),
        inputs=default_input_curriculum(),
        loss_policy=default_loss_policy(),
        trainers=default_trainer_contracts(),
        comparison_metrics=tuple(ComparisonMetric),
    )


class SFTCurriculumTests(unittest.TestCase):
    def test_all_fourteen_gtm_stages_are_complete_and_canonical(self) -> None:
        item = contract()
        self.assertEqual(tuple(stage.stage for stage in item.stages), CANONICAL_STAGE_ORDER)
        self.assertEqual(len(item.stages), 14)
        self.assertTrue(all(stage.required_outputs for stage in item.stages))
        self.assertTrue(all("unsupported_claim" in stage.forbidden_shortcuts for stage in item.stages))

    def test_nine_input_phases_grow_from_short_text_to_cross_channel(self) -> None:
        phases = contract().inputs
        self.assertEqual(tuple(item.input_kind for item in phases), CANONICAL_INPUT_ORDER)
        for index, phase in enumerate(phases):
            self.assertEqual(phase.minimum_preceding_kinds, CANONICAL_INPUT_ORDER[:index])
        self.assertFalse(phases[0].evidence_required)
        self.assertTrue(all(item.evidence_required for item in phases[1:]))

    def test_claim_locator_smp_rtb_big_idea_json_and_stop_are_emphasized(self) -> None:
        policy = contract().loss_policy
        self.assertEqual(
            set(policy.positive_token_weights),
            {"claim", "locator", "smp", "rtb", "big_idea", "json", "stop"},
        )
        self.assertTrue(all(weight > 1 for weight in policy.positive_token_weights.values()))

    def test_unsafe_actions_are_never_positive_targets(self) -> None:
        policy = contract().loss_policy
        self.assertEqual(policy.unsafe_action_target_weight, 0.0)
        self.assertGreater(policy.unsafe_action_unlikelihood_weight, 1.0)


class SFTTrainerAndReplayTests(unittest.TestCase):
    def test_ordinary_sft_and_dft_are_distinct_test_blind_contracts(self) -> None:
        trainers = {item.variant: item for item in contract().trainers}
        self.assertFalse(trainers[TrainerVariant.SFT].token_weighting)
        self.assertTrue(trainers[TrainerVariant.DFT].token_weighting)
        self.assertTrue(trainers[TrainerVariant.DFT].negative_unlikelihood_loss)
        self.assertTrue(all(not item.test_split_visible for item in trainers.values()))

    def test_stage_artifacts_bind_adapter_data_metrics_and_previous_stage(self) -> None:
        replay = build_controlled_replay(CANONICAL_STAGE_ORDER[:4])
        self.assertEqual(len(replay.artifacts), 4)
        for artifact in replay.artifacts:
            self.assertEqual(len(artifact.adapter_sha256), 64)
            self.assertEqual(len(artifact.data_sha256), 64)
            self.assertEqual(len(artifact.metrics_sha256), 64)
            self.assertFalse(artifact.observed_training)
        self.assertEqual(len(replay.digest), 64)

    def test_stage_rollback_and_multistage_replay_fail_closed_on_tamper(self) -> None:
        replay = build_controlled_replay(CANONICAL_STAGE_ORDER[:5])
        rolled = replay.rollback(CurriculumStage.CREATIVE)
        self.assertEqual(rolled[-1].stage, CurriculumStage.CREATIVE)
        damaged = StageArtifact(
            **{
                **replay.artifacts[2].__dict__,
                "previous_stage_digest": "f" * 64,
            }
        )
        with self.assertRaisesRegex(V10ContractError, "hash chain"):
            StageReplay((replay.artifacts[0], replay.artifacts[1], damaged))

    def test_planned_card_keeps_all_training_and_control_results_unknown(self) -> None:
        card = planned_sft_card(contract())
        self.assertFalse(card["training_observed"])
        self.assertFalse(card["promotion_eligible"])
        for key in (
            "ordinary_sft_metrics",
            "dft_metrics",
            "random_order_control",
            "reverse_curriculum_control",
            "curriculum_gain",
            "selected_adapter",
        ):
            self.assertIsNone(card[key])
        self.assertEqual(len(card["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
