from __future__ import annotations

import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_cpt_contract import (
    BaseRevision,
    CPTContract,
    CPTExecutionSettings,
    CPTObjective,
    CheckpointMetrics,
    LearningRatePolicy,
    ModelProfile,
    MonitorMetric,
    RadeonMemoryObservation,
    ResumeCheckpoint,
    default_mix_schedule,
    default_objectives,
    planned_cpt_card,
    select_best_checkpoint,
    select_profile,
)


def base() -> BaseRevision:
    return BaseRevision(
        model_id="google/gemma-4-E4B-it",
        revision="1fe35ce743b357484b97a11646125adffee0b410",
        config_sha256="33b10c02df3c2e8536cf323d29d53262aaa2f4d11dbe19bc729373fbe90295d4",
        tokenizer_sha256="cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
        processor_sha256="32bdf45d2ad4cc29a0822ddd157a182de76644f0419a6228d151495256e9813c",
        artifact_hashes_observed=True,
    )


def settings() -> CPTExecutionSettings:
    return CPTExecutionSettings(
        packing=True,
        packing_resets_position_and_attention=True,
        gradient_checkpointing=True,
        gradient_accumulation_steps=8,
        bf16=True,
        deterministic_seed=42,
        maximum_wall_clock_hours=6.0,
        checkpoint_interval_steps=100,
        save_optimizer=True,
        save_scheduler=True,
        save_rng_state=True,
    )


def contract() -> CPTContract:
    return CPTContract(
        base=base(),
        profile=ModelProfile.E4B,
        objectives=default_objectives(),
        schedule=default_mix_schedule(),
        learning_rates=LearningRatePolicy(
            vision_tower=0.0,
            connector=2e-4,
            language_model=2e-5,
            adapter=1e-4,
        ),
        settings=settings(),
        monitor_metrics=tuple(MonitorMetric),
    )


def metrics(
    checkpoint_id: str,
    step: int,
    *,
    state: float,
    claim: float = 0.97,
    visual: float = 0.98,
) -> CheckpointMetrics:
    return CheckpointMetrics(
        checkpoint_id=checkpoint_id,
        step=step,
        train_loss=0.8,
        validation_loss=0.9,
        visual_retention=visual,
        language_retention=0.98,
        schema_validity=0.99,
        claim_grounding=claim,
        state_prediction=state,
    )


class CPTObjectiveAndProfileTests(unittest.TestCase):
    def test_base_revision_and_all_twelve_objectives_are_frozen(self) -> None:
        item = contract()
        self.assertEqual(item.base.revision, "1fe35ce743b357484b97a11646125adffee0b410")
        self.assertTrue(item.base.artifact_hashes_observed)
        self.assertEqual(
            item.base.tokenizer_sha256,
            "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
        )
        self.assertEqual(len(item.objectives), 12)
        self.assertEqual({objective.objective for objective in item.objectives}, set(CPTObjective))
        self.assertTrue(all(objective.negative_control for objective in item.objectives))
        self.assertEqual(len(item.digest), 64)

    def test_observed_rocm_vram_selects_4b_or_2b_and_unobserved_data_is_rejected(self) -> None:
        def observation(free: float, observed: bool = True):
            return RadeonMemoryObservation(
                backend="rocm",
                device_name="Radeon fixture",
                total_vram_gb=64,
                free_vram_gb=free,
                receipt_sha256="d" * 64,
                observed=observed,
            )
        self.assertEqual(select_profile(observation(48)), ModelProfile.E4B)
        self.assertEqual(select_profile(observation(24)), ModelProfile.E2B)
        with self.assertRaisesRegex(V10ContractError, "observed Radeon VRAM"):
            select_profile(observation(48, observed=False))


class CPTScheduleAndStateTests(unittest.TestCase):
    def test_modality_task_mix_and_three_stage_schedule_are_complete(self) -> None:
        schedule = default_mix_schedule()
        self.assertEqual([(item.start_fraction, item.end_fraction) for item in schedule], [(0.0, 0.35), (0.35, 0.75), (0.75, 1.0)])
        for stage in schedule:
            self.assertAlmostEqual(sum(stage.modality_mix.values()), 1.0)
            self.assertAlmostEqual(sum(stage.task_mix.values()), 1.0)
            self.assertEqual(set(stage.task_mix), set(CPTObjective))

    def test_lr_packing_checkpointing_accumulation_bf16_seed_budget_and_interval_are_locked(self) -> None:
        item = contract()
        self.assertEqual(item.learning_rates.vision_tower, 0.0)
        self.assertGreaterEqual(item.learning_rates.connector, item.learning_rates.adapter)
        self.assertGreaterEqual(item.learning_rates.adapter, item.learning_rates.language_model)
        self.assertTrue(item.settings.packing and item.settings.packing_resets_position_and_attention)
        self.assertTrue(item.settings.gradient_checkpointing and item.settings.bf16)
        self.assertEqual(item.settings.gradient_accumulation_steps, 8)
        self.assertEqual(item.settings.deterministic_seed, 42)
        self.assertEqual(item.settings.maximum_wall_clock_hours, 6.0)
        self.assertEqual(item.settings.checkpoint_interval_steps, 100)

    def test_resume_checkpoint_requires_model_optimizer_scheduler_rng_and_data_revision(self) -> None:
        checkpoint = ResumeCheckpoint(
            checkpoint_id="cpt-step-100",
            step=100,
            model_sha256="a" * 64,
            optimizer_sha256="b" * 64,
            scheduler_sha256="c" * 64,
            rng_state_sha256="d" * 64,
            data_revision="curated-corpus-v2@frozen",
        )
        self.assertEqual(checkpoint.step, 100)
        with self.assertRaisesRegex(V10ContractError, "rng_state_sha256"):
            ResumeCheckpoint(**{**checkpoint.__dict__, "rng_state_sha256": "missing"})


class CPTMonitoringAndSelectionTests(unittest.TestCase):
    def test_monitor_contract_covers_loss_retention_schema_claim_and_state(self) -> None:
        self.assertEqual(
            set(contract().monitor_metrics),
            {
                MonitorMetric.TRAIN_LOSS,
                MonitorMetric.VALIDATION_LOSS,
                MonitorMetric.VISUAL_RETENTION,
                MonitorMetric.LANGUAGE_RETENTION,
                MonitorMetric.SCHEMA_VALIDITY,
                MonitorMetric.CLAIM_GROUNDING,
                MonitorMetric.STATE_PREDICTION,
            },
        )

    def test_best_checkpoint_is_gate_first_and_never_defaults_to_last(self) -> None:
        selection = select_best_checkpoint(
            (
                metrics("step-100", 100, state=0.95),
                metrics("step-200", 200, state=0.91),
                metrics("step-300", 300, state=0.99, visual=0.90),
            )
        )
        self.assertEqual(selection.selected_checkpoint_id, "step-100")
        self.assertEqual(selection.last_checkpoint_id, "step-300")
        self.assertFalse(selection.selected_is_last)
        self.assertIn("step-300", selection.rejected)
        self.assertEqual(len(selection.digest), 64)

    def test_cpt_card_exposes_unknown_runtime_metrics_instead_of_zero_fabrication(self) -> None:
        card = planned_cpt_card(contract())
        self.assertFalse(card["training_observed"])
        self.assertFalse(card["promotion_eligible"])
        for key in (
            "selected_checkpoint", "throughput_tokens_per_second", "peak_vram_gb",
            "energy_proxy", "data_revision", "learning_curve",
        ):
            self.assertIsNone(card[key])
        self.assertEqual(len(card["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
