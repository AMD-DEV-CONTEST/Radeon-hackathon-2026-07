from __future__ import annotations

from pathlib import Path
import unittest

from scripts.run_grasp_scorer_v2_pipeline import (
    dataset_group_counts,
    load_model_protocol,
    training_commands,
    validate_dataset_groups,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = PROJECT_ROOT / "configs/grasp_candidate_model_selection_v2.toml"


class GraspScorerV2PipelineTests(unittest.TestCase):
    def test_builds_two_capacity_matched_training_commands(self) -> None:
        protocol = load_model_protocol(PROTOCOL)

        commands = training_commands(
            protocol,
            python="python",
            dataset=Path("dataset.json"),
            output_dir=Path("models"),
        )

        self.assertEqual([name for name, _command in commands], [
            "pointwise",
            "groupwise-safety-first",
        ])
        pointwise = commands[0][1]
        groupwise = commands[1][1]
        for flag in (
            "--steps",
            "--hidden-width",
            "--learning-rate",
            "--weight-decay",
            "--seed",
            "--device",
        ):
            self.assertEqual(
                pointwise[pointwise.index(flag) + 1],
                groupwise[groupwise.index(flag) + 1],
            )
        self.assertEqual(
            pointwise[pointwise.index("--objective") + 1],
            "pointwise",
        )
        self.assertEqual(
            groupwise[groupwise.index("--objective") + 1],
            "groupwise-safety-first",
        )

    def test_validates_group_counts_without_row_count_confusion(self) -> None:
        payload = {
            "rows": [
                {"group_id": "a:1", "split": "train"},
                {"group_id": "a:1", "split": "train"},
                {"group_id": "b:2", "split": "development"},
            ]
        }

        self.assertEqual(
            dataset_group_counts(payload),
            {"train": 1, "development": 1},
        )
        with self.assertRaisesRegex(ValueError, "group counts differ"):
            validate_dataset_groups(payload, {"train": 2, "development": 1})

    def test_rejects_group_crossing_splits(self) -> None:
        payload = {
            "rows": [
                {"group_id": "a:1", "split": "train"},
                {"group_id": "a:1", "split": "development"},
            ]
        }

        with self.assertRaisesRegex(ValueError, "crosses splits"):
            dataset_group_counts(payload)


if __name__ == "__main__":
    unittest.main()
