import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from parcel_sorter.mobile_self_improvement_cycle import (
    build_curriculum_config,
    build_frozen_holdout_config,
    build_randomized_mobile_campaign_config,
    build_replay_from_campaign_audit,
    promotion_gate,
    validate_paired_campaigns,
    validate_split_isolation,
)
from scripts.collect_mobile_suction_dataset_rocm import _cli_float, _write_json


def _audit(*, successes: int, force_violations: int = 0) -> dict:
    trials = 100
    return {
        "status": "passed",
        "successes": successes,
        "trials": trials,
        "success_rate": successes / trials,
        "wilson_95": [0.70, 0.86],
        "force_violation_count": force_violations,
        "vla_actuated_run_count": trials,
        "single_radeon_rocm_run_count": trials,
    }


class MobileSelfImprovementCycleTests(unittest.TestCase):
    def test_paired_gate_requires_identical_ordered_physics(self) -> None:
        runs = [
            {
                "profile": "small_carton",
                "parameters": {
                    "size_m": [0.2, 0.12, 0.2],
                    "mass_kg": 0.4,
                    "friction": 0.8,
                    "offset_m": [0.0, 0.0],
                },
            },
            {
                "profile": "flat_mailer",
                "parameters": {
                    "size_m": [0.22, 0.15, 0.08],
                    "mass_kg": 0.3,
                    "friction": 0.6,
                    "offset_m": [0.005, -0.004],
                },
            },
        ]
        pairing = validate_paired_campaigns({"runs": runs}, {"runs": list(runs)})
        self.assertEqual(pairing["paired_trials"], 2)
        with self.assertRaises(ValueError):
            validate_paired_campaigns({"runs": runs}, {"runs": list(reversed(runs))})

    def test_builds_balanced_outcome_blind_development_campaign(self) -> None:
        config = build_randomized_mobile_campaign_config(
            campaign_id="arm-residual-dev-v1",
            episode_prefix="arm-dev",
            split="development_do_not_train",
            trials=12,
            seed=20260729,
        )
        self.assertEqual(len(config["episodes"]), 12)
        counts = {
            profile: sum(item["profile"] == profile for item in config["episodes"])
            for profile in {item["profile"] for item in config["episodes"]}
        }
        self.assertEqual(set(counts.values()), {3})
        self.assertNotIn("success", str(config))

    def test_cli_float_never_uses_exponent_syntax(self) -> None:
        self.assertEqual(_cli_float(-9e-05), "-0.00009")
        self.assertEqual(_cli_float(0.0), "0")

    def test_campaign_summary_write_is_atomic(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "collection-summary.json"
            _write_json(output, {"status": "collecting", "completed_episodes": 7})
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                '{\n  "status": "collecting",\n  "completed_episodes": 7\n}',
            )
            self.assertFalse((output.parent / f".{output.name}.tmp").exists())

    def test_failure_becomes_bridge_and_consumes_source_holdout(self) -> None:
        source = {
            "collection_summary_sha256": "a" * 64,
            "runs": [
                {
                    "episode_id": "heavy-104",
                    "profile": "medium_carton",
                    "success": False,
                    "failure_stage": "lift_success",
                    "parameters": {
                        "episode_id": "heavy-104",
                        "profile": "medium_carton",
                        "size_m": [0.255, 0.155, 0.205],
                        "mass_kg": 0.72,
                        "friction": 0.9,
                        "offset_m": [0.009, -0.009],
                    },
                    "suction": {"max_contact_force_n": 4.6},
                }
            ],
        }
        replay = build_replay_from_campaign_audit(source)
        self.assertTrue(replay["source_campaign_consumed_for_development"])
        self.assertEqual(replay["items"][0]["curriculum_bridge"]["mass_kg"], 0.648)
        base = {"collection_id": "base", "episodes": [{"episode_id": "base-0"}]}
        curriculum = build_curriculum_config(base, replay, cycle_id="v3")
        self.assertEqual(len(curriculum["episodes"]), 2)
        self.assertEqual(curriculum["episodes"][1]["source_failure_episode_id"], "heavy-104")

    def test_holdout_is_deterministic_balanced_and_disjoint(self) -> None:
        first = build_frozen_holdout_config(cycle_id="v3", trials=100, seed=7)
        second = build_frozen_holdout_config(cycle_id="v3", trials=100, seed=7)
        self.assertEqual(first, second)
        training = {
            "episodes": [
                {
                    "episode_id": "train-0",
                    "profile": "small_carton",
                    "size_m": [0.2, 0.12, 0.2],
                    "mass_kg": 0.4,
                    "friction": 0.8,
                    "offset_m": [0.0, 0.0],
                }
            ]
        }
        audit = validate_split_isolation(training, first)
        self.assertEqual(audit["holdout_episodes"], 100)
        self.assertEqual(audit["profile_counts"], {name: 25 for name in audit["profile_counts"]})

    def test_promotion_requires_performance_safety_actuation_and_rocm(self) -> None:
        baseline = _audit(successes=78)
        candidate = _audit(successes=82)
        self.assertTrue(promotion_gate(baseline, candidate)["promoted"])
        candidate["force_violation_count"] = 1
        self.assertFalse(promotion_gate(baseline, candidate)["promoted"])
        candidate = _audit(successes=79)
        self.assertFalse(promotion_gate(baseline, candidate)["promoted"])


if __name__ == "__main__":
    unittest.main()
