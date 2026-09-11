import unittest

from parcel_sorter.evaluation import aggregate_checkpoint_evaluations


def _payload(
    checkpoint: str,
    episode_index: int,
    success: bool,
    latency: float,
    *,
    profile_id: str = "small_carton",
    max_force_n: float = 12.0,
    safety_threshold_n: float = 35.0,
) -> dict:
    return {
        "checkpoint": checkpoint,
        "config": {"task": {"max_contact_force_n": safety_threshold_n}},
        "episodes": [
            {
                "episode_index": episode_index,
                "sample": {"profile_id": profile_id},
                "result": {
                    "success": success,
                    "retries": 0,
                    "duration_seconds": 2.0,
                    "inference_latency_ms": [latency],
                    "dropped": False,
                    "max_contact_force_n": max_force_n,
                },
            }
        ],
    }


class CheckpointEvaluationTests(unittest.TestCase):
    def test_non_overlapping_ranges_are_combined(self) -> None:
        records = [
            ("a.json", _payload("checkpoint-4000", 10, True, 2.0)),
            ("b.json", _payload("checkpoint-4000", 11, False, 4.0)),
        ]

        aggregate = aggregate_checkpoint_evaluations(records)[0]

        self.assertEqual(aggregate.episodes, 2)
        self.assertEqual(aggregate.episode_indices, (10, 11))
        self.assertEqual(aggregate.success_rate, 0.5)
        self.assertEqual(aggregate.successes, 1)
        self.assertEqual(aggregate.macro_profile_success_rate, 0.5)
        self.assertLess(aggregate.success_rate_ci95_low, 0.5)
        self.assertGreater(aggregate.success_rate_ci95_high, 0.5)
        self.assertEqual(len(aggregate.evaluation_manifest_sha256), 64)
        self.assertEqual(aggregate.mean_inference_latency_ms, 3.0)

    def test_duplicate_episode_is_rejected(self) -> None:
        records = [
            ("a.json", _payload("checkpoint-4000", 10, True, 2.0)),
            ("b.json", _payload("checkpoint-4000", 10, False, 4.0)),
        ]

        with self.assertRaisesRegex(ValueError, "repeats episode 10"):
            aggregate_checkpoint_evaluations(records)

    def test_task_success_has_priority_over_latency(self) -> None:
        records = [
            ("slow.json", _payload("checkpoint-4000", 10, True, 8.0)),
            ("fast.json", _payload("checkpoint-5000", 10, False, 1.0)),
        ]

        ranked = aggregate_checkpoint_evaluations(records)

        self.assertEqual(ranked[0].checkpoint, "checkpoint-4000")

    def test_mismatched_candidate_episode_sets_are_rejected(self) -> None:
        records = [
            ("a.json", _payload("checkpoint-4000", 10, True, 2.0)),
            ("b.json", _payload("checkpoint-5000", 11, True, 2.0)),
        ]

        with self.assertRaisesRegex(ValueError, "identical episode sets"):
            aggregate_checkpoint_evaluations(records)

    def test_safety_gate_has_priority_over_success(self) -> None:
        records = [
            (
                "unsafe.json",
                _payload(
                    "checkpoint-unsafe",
                    10,
                    True,
                    2.0,
                    max_force_n=36.0,
                ),
            ),
            ("safe.json", _payload("checkpoint-safe", 10, False, 2.0)),
        ]

        ranked = aggregate_checkpoint_evaluations(records)

        self.assertEqual(ranked[0].checkpoint, "checkpoint-safe")
        self.assertEqual(ranked[1].safety_violations, 1)

    def test_profile_macro_average_is_reported(self) -> None:
        records = [
            ("a.json", _payload("checkpoint-4000", 10, True, 2.0, profile_id="box")),
            ("b.json", _payload("checkpoint-4000", 11, True, 2.0, profile_id="box")),
            ("c.json", _payload("checkpoint-4000", 12, False, 2.0, profile_id="tube")),
        ]

        aggregate = aggregate_checkpoint_evaluations(records)[0]

        self.assertAlmostEqual(aggregate.success_rate, 2 / 3)
        self.assertAlmostEqual(aggregate.macro_profile_success_rate, 0.5)
        self.assertEqual(aggregate.profile_summaries["tube"]["episodes"], 1)

    def test_mismatched_safety_thresholds_are_rejected(self) -> None:
        records = [
            ("a.json", _payload("checkpoint-4000", 10, True, 2.0)),
            (
                "b.json",
                _payload(
                    "checkpoint-5000",
                    10,
                    True,
                    2.0,
                    safety_threshold_n=40.0,
                ),
            ),
        ]

        with self.assertRaisesRegex(ValueError, "same contact-force"):
            aggregate_checkpoint_evaluations(records)

    def test_same_episode_id_with_different_sample_is_rejected(self) -> None:
        left = _payload("checkpoint-4000", 10, True, 2.0, profile_id="box")
        right = _payload("checkpoint-5000", 10, True, 2.0, profile_id="tube")

        with self.assertRaisesRegex(ValueError, "identical randomized episode samples"):
            aggregate_checkpoint_evaluations(
                [("left.json", left), ("right.json", right)]
            )


if __name__ == "__main__":
    unittest.main()
