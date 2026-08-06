from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_training import (
    DataRight,
    DataSplit,
    JudgeCalibration,
    PreferenceEvidence,
    TrainingCorpusManifest,
    TrainingPhase,
    TrainingPhaseStatus,
    TrainingRunState,
    TrainingSample,
    default_v10_training_plan,
)


ROOT = Path(__file__).resolve().parents[1]


def sample(
    sample_id: str,
    digest_char: str,
    split: DataSplit,
    captured_at: str,
    *,
    right: DataRight = DataRight.OWNED,
) -> TrainingSample:
    return TrainingSample(
        sample_id=sample_id,
        content_sha256=digest_char * 64,
        task_family="grounded_campaign",
        modalities=("text", "image"),
        source_locator=f"dataset://{sample_id}",
        source_right=right,
        license_id="owned-v1",
        split=split,
        captured_at=captured_at,
    )


class CorpusContractTests(unittest.TestCase):
    def test_clean_temporal_rights_manifest_passes(self) -> None:
        manifest = TrainingCorpusManifest(
            samples=(
                sample("train", "a", DataSplit.TRAIN, "2026-06-01T00:00:00Z"),
                sample(
                    "validation",
                    "b",
                    DataSplit.VALIDATION,
                    "2026-06-15T00:00:00Z",
                ),
                sample("test", "c", DataSplit.TEST, "2026-07-02T00:00:00Z"),
            ),
            temporal_holdout_start="2026-07-01T00:00:00Z",
        )
        self.assertTrue(manifest.audit().passed)
        self.assertEqual(len(manifest.digest), 64)

    def test_duplicate_content_and_unknown_rights_fail(self) -> None:
        manifest = TrainingCorpusManifest(
            samples=(
                sample("train", "a", DataSplit.TRAIN, "2026-06-01T00:00:00Z"),
                sample(
                    "validation",
                    "a",
                    DataSplit.VALIDATION,
                    "2026-06-02T00:00:00Z",
                    right=DataRight.UNKNOWN,
                ),
                sample("test", "c", DataSplit.TEST, "2026-07-02T00:00:00Z"),
            ),
            temporal_holdout_start="2026-07-01T00:00:00Z",
        )
        audit = manifest.audit()
        self.assertFalse(audit.passed)
        self.assertIn(
            "content hash leakage or duplication across splits",
            audit.failures,
        )

    def test_train_data_cannot_cross_strict_time_holdout(self) -> None:
        manifest = TrainingCorpusManifest(
            samples=(
                sample("train", "a", DataSplit.TRAIN, "2026-07-02T00:00:00Z"),
                sample(
                    "validation",
                    "b",
                    DataSplit.VALIDATION,
                    "2026-06-02T00:00:00Z",
                ),
                sample("test", "c", DataSplit.TEST, "2026-07-03T00:00:00Z"),
            ),
            temporal_holdout_start="2026-07-01T00:00:00Z",
        )
        self.assertFalse(manifest.audit().passed)


class TrainingPlanTests(unittest.TestCase):
    def test_plan_has_six_sequential_multigpu_radeon_stages(self) -> None:
        plan = default_v10_training_plan()
        self.assertEqual(tuple(stage.phase for stage in plan.stages), tuple(TrainingPhase))
        self.assertTrue(plan.radeon_required)
        self.assertTrue(plan.multi_gpu_required)
        self.assertEqual(plan.minimum_world_size, 2)
        self.assertEqual(plan.preferred_world_size, 4)
        self.assertEqual(plan.preferred_strategy, "ddp")
        self.assertEqual(plan.memory_fallback_strategy, "fsdp2")
        self.assertTrue(plan.single_gpu_baseline_required)
        self.assertFalse(plan.single_gpu_may_promote)
        self.assertEqual(plan.maximum_resident_heavy_models_per_rank, 1)
        self.assertEqual(plan.expected_global_batch_size, 16)
        self.assertGreaterEqual(plan.cold_launch_trials, 3)
        self.assertGreaterEqual(plan.checkpoint_resume_trials, 2)
        self.assertGreaterEqual(plan.two_gpu_minimum_speedup, 1.5)
        self.assertGreaterEqual(plan.minimum_parallel_efficiency, 0.70)
        self.assertLessEqual(
            sum(stage.maximum_gpu_hours for stage in plan.stages),
            plan.maximum_total_gpu_hours,
        )
        self.assertTrue(
            all("vision_tower" in stage.frozen_modules for stage in plan.stages)
        )

    def test_serialized_multigpu_plan_is_content_addressed(self) -> None:
        payload = json.loads(
            (
                ROOT / "config" / "cortex_x_v10_training_plan.json"
            ).read_text(encoding="utf-8")
        )
        expected_hash = payload.pop("contract_sha256")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected_hash)
        distributed = payload["distributed_execution"]
        self.assertTrue(distributed["multi_gpu_required"])
        self.assertEqual(distributed["minimum_world_size"], 2)
        self.assertEqual(distributed["preferred_world_size"], 4)
        self.assertEqual(distributed["preferred_strategy"], "ddp")
        self.assertEqual(distributed["memory_fallback_strategy"], "fsdp2")
        self.assertFalse(distributed["single_gpu_may_promote"])

    def test_run_cannot_skip_curriculum_phase(self) -> None:
        state = TrainingRunState(default_v10_training_plan(), "a" * 64)
        with self.assertRaises(V10ContractError):
            state.start(TrainingPhase.CURRICULUM_SFT)

    def test_failed_retention_gate_rolls_back(self) -> None:
        state = TrainingRunState(default_v10_training_plan(), "a" * 64)
        state.start(TrainingPhase.MULTIMODAL_CPT)
        status = state.finish(
            TrainingPhase.MULTIMODAL_CPT,
            checkpoint_sha256="b" * 64,
            metrics={"general_multimodal_regression": 0.006},
        )
        self.assertEqual(status, TrainingPhaseStatus.ROLLED_BACK)
        self.assertNotIn(TrainingPhase.MULTIMODAL_CPT, state.checkpoint_sha256)

    def test_judge_calibration_requires_more_than_eighty_percent_each_side(self) -> None:
        plan = default_v10_training_plan()
        boundary = JudgeCalibration(40, 10, 40, 10)
        strong = JudgeCalibration(41, 9, 41, 9)
        self.assertFalse(boundary.passes(plan))
        self.assertTrue(strong.passes(plan))

    def test_preference_gate_uses_raw_counts_and_wilson_bound(self) -> None:
        weak = PreferenceEvidence(119, 150)
        strong = PreferenceEvidence(130, 150)
        self.assertFalse(weak.passes_v10)
        self.assertTrue(strong.passes_v10)


if __name__ == "__main__":
    unittest.main()
