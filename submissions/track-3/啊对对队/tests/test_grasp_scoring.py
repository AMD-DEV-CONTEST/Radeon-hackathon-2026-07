from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from parcel_sorter.grasp_scoring import (
    GRASP_FEATURE_NAMES,
    build_grasp_candidate_dataset,
    counterfactual_rows,
    evaluate_ranked_grasp_predictions,
    grasp_candidate_feature_vector,
    grasp_prediction_rank_key,
    grouped_grasp_row_indices,
    groupwise_grasp_preference_pairs,
    load_grasp_collection_activation_policy,
    load_grasp_split_protocol,
)


def payload() -> dict:
    return {
        "profile": "medium_carton",
        "episode": 42,
        "sample": {
            "dimensions_m": [0.2, 0.1, 0.12],
            "mass_kg": 0.5,
            "friction": 0.6,
            "rolling_friction": 0.0,
            "position_xy": [0.6, -0.02],
            "yaw_rad": 0.5,
            "action_delay_steps": 2,
            "destination": "right",
        },
        "contract": {
            "controller_faithful": True,
            "fresh_scene_per_rollout": True,
            "force_abort_n": 35.0,
        },
        "static_feasible_candidates": [
            {
                "candidate_id": "candidate-a",
                "seed_name": "current",
                "static_rank": 3,
                "target_position": [0.6, -0.02, 0.2],
                "target_quaternion": [0.0, 1.0, 0.0, 0.0],
                "longitudinal_offset_m": 0.0,
                "vertical_offset_m": 0.045,
                "wrist_variant": "canonical",
                "minimum_singular_value": 0.1,
                "joint_distance_rad": 1.2,
                "nonfinger_clearance_m": 0.01,
                "disallowed_collision_count": 0,
            }
        ],
        "rollouts": [
            {
                "candidate_id": "candidate-a",
                "selected_candidate_id": "candidate-a",
                "repeat": 0,
                "static_rank": 3,
                "success": True,
                "safety_aborted": False,
                "max_contact_force_n": 12.0,
                "duration_seconds": 8.0,
            }
        ],
    }


class GraspScoringTests(unittest.TestCase):
    def test_extracts_versioned_finite_feature_vector(self) -> None:
        source = payload()
        features = grasp_candidate_feature_vector(source, source["rollouts"][0])

        self.assertEqual(len(features), len(GRASP_FEATURE_NAMES))
        self.assertAlmostEqual(features[GRASP_FEATURE_NAMES.index("target_dx_m")], 0.0)
        self.assertEqual(features[GRASP_FEATURE_NAMES.index("destination_side")], 1.0)

    def test_builds_auditable_dataset(self) -> None:
        dataset = build_grasp_candidate_dataset(
            (("source.json", payload(), "a" * 64, "smoke"),)
        )

        self.assertEqual(dataset["row_count"], 1)
        self.assertEqual(dataset["group_count"], 1)
        self.assertEqual(dataset["splits"], {"smoke": 1})
        self.assertEqual(len(dataset["dataset_sha256"]), 64)

    def test_dataset_rejects_duplicate_label_across_sources(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate grasp label across sources"):
            build_grasp_candidate_dataset(
                (
                    ("source-a.json", payload(), "a" * 64, "smoke"),
                    ("source-b.json", payload(), "b" * 64, "smoke"),
                )
            )

    def test_rejects_requested_selected_or_force_label_mismatch(self) -> None:
        source = payload()
        source["rollouts"][0]["selected_candidate_id"] = "candidate-b"
        with self.assertRaisesRegex(ValueError, "requested/selected"):
            counterfactual_rows(source, source="source.json", split="smoke")

        source = payload()
        source["rollouts"][0]["safety_aborted"] = True
        with self.assertRaisesRegex(ValueError, "force-abort label mismatch"):
            counterfactual_rows(source, source="source.json", split="smoke")

    def test_rejects_structured_inactive_gate_skip_as_training_data(self) -> None:
        source = payload()
        source["status"] = "skipped_inactive_reset_gate"
        source["rollouts"] = []

        with self.assertRaisesRegex(ValueError, "did not generate labels"):
            counterfactual_rows(source, source="source.json", split="train")

    def test_prediction_ranking_prioritizes_safety(self) -> None:
        safe_failure = {
            "candidate_id": "safe",
            "static_rank": 2,
            "unsafe_probability": 0.01,
            "success_probability": 0.1,
            "predicted_force_n": 10.0,
            "predicted_duration_seconds": 20.0,
        }
        risky_success = {
            "candidate_id": "risky",
            "static_rank": 0,
            "unsafe_probability": 0.8,
            "success_probability": 0.99,
            "predicted_force_n": 8.0,
            "predicted_duration_seconds": 5.0,
        }

        ranked = sorted((risky_success, safe_failure), key=grasp_prediction_rank_key)

        self.assertEqual(ranked[0]["candidate_id"], "safe")

    def test_groupwise_pairs_preserve_lexicographic_safety(self) -> None:
        rows = [
            {
                "group_id": "b",
                "labels": {"safety_aborted": False, "success": True},
            },
            {
                "group_id": "a",
                "labels": {"safety_aborted": False, "success": False},
            },
            {
                "group_id": "a",
                "labels": {"safety_aborted": True, "success": False},
            },
            {
                "group_id": "a",
                "labels": {"safety_aborted": False, "success": True},
            },
            {
                "group_id": "b",
                "labels": {"safety_aborted": False, "success": False},
            },
        ]

        self.assertEqual(grouped_grasp_row_indices(rows), ((1, 2, 3), (0, 4)))
        pairs = groupwise_grasp_preference_pairs(rows)

        self.assertEqual(pairs["safety"], (((1, 2), (3, 2)),))
        self.assertEqual(pairs["success"], (((3, 1),), ((0, 4),)))

    def test_groupwise_pairs_reject_missing_group_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "group_id"):
            grouped_grasp_row_indices(
                [{"labels": {"safety_aborted": False, "success": True}}]
            )

    def test_evaluation_rejects_prediction_order_mismatch(self) -> None:
        rows = counterfactual_rows(payload(), source="source.json", split="smoke")
        prediction = {
            "candidate_id": "candidate-b",
            "static_rank": 3,
            "unsafe_probability": 0.1,
            "success_probability": 0.9,
            "predicted_force_n": 12.0,
            "predicted_duration_seconds": 8.0,
        }
        with self.assertRaisesRegex(ValueError, "candidate order"):
            evaluate_ranked_grasp_predictions(rows, (prediction,))

    def test_evaluation_reports_paired_and_profile_metrics(self) -> None:
        rows = [
            {
                "group_id": "medium_carton:1",
                "profile": "medium_carton",
                "candidate_id": "baseline",
                "static_rank": 0,
                "labels": {
                    "success": False,
                    "safety_aborted": True,
                    "max_contact_force_n": 40.0,
                    "duration_seconds": 5.0,
                },
            },
            {
                "group_id": "medium_carton:1",
                "profile": "medium_carton",
                "candidate_id": "learned",
                "static_rank": 1,
                "labels": {
                    "success": True,
                    "safety_aborted": False,
                    "max_contact_force_n": 12.0,
                    "duration_seconds": 8.0,
                },
            },
        ]
        predictions = [
            {
                "candidate_id": "baseline",
                "static_rank": 0,
                "unsafe_probability": 0.9,
                "success_probability": 0.1,
                "predicted_force_n": 40.0,
                "predicted_duration_seconds": 5.0,
            },
            {
                "candidate_id": "learned",
                "static_rank": 1,
                "unsafe_probability": 0.1,
                "success_probability": 0.9,
                "predicted_force_n": 12.0,
                "predicted_duration_seconds": 8.0,
            },
        ]

        result = evaluate_ranked_grasp_predictions(rows, predictions)

        self.assertEqual(result["success_gains"], 1)
        self.assertEqual(result["safety_abort_reductions"], 1)
        self.assertEqual(result["safety_abort_regressions"], 0)
        self.assertEqual(result["model_mean_force_n"], 12.0)
        self.assertEqual(
            result["per_profile"]["medium_carton"]["baseline_mean_force_n"],
            40.0,
        )

    def test_protocol_rejects_overlapping_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protocol.toml"
            path.write_text(
                """
[[splits]]
name = "train"
profile_id = "medium_carton"
episode_ids = [42]

[[splits]]
name = "holdout"
profile_id = "medium_carton"
episode_ids = [42]
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate grasp split"):
                load_grasp_split_protocol(path)

    def test_collection_activation_policy_is_frozen_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protocol.toml"
            path.write_text(
                '[[splits]]\nname = "train"\nprofile_id = "medium_carton"\n'
                "episode_ids = [1]\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_grasp_collection_activation_policy(path),
                "reset-fallback",
            )

            path.write_text(
                '[collection]\nplanning_activation_policy = "geometry-eligible"\n\n'
                '[[splits]]\nname = "train"\nprofile_id = "medium_carton"\n'
                "episode_ids = [1]\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_grasp_collection_activation_policy(path),
                "geometry-eligible",
            )

            path.write_text(
                '[collection]\nplanning_activation_policy = "outcome-selected"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported"):
                load_grasp_collection_activation_policy(path)


if __name__ == "__main__":
    unittest.main()
