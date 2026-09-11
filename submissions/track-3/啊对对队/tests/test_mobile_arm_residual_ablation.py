import unittest

from parcel_sorter.mobile_arm_residual_ablation import (
    evaluate_arm_residual_development_gate,
    evaluate_arm_residual_holdout_gate,
)


def _audit(
    *,
    candidate: bool,
    failures: set[int] | None = None,
    pretransport_failures: set[int] | None = None,
) -> dict:
    failures = failures or set()
    pretransport_failures = pretransport_failures or set()
    runs = []
    for index in range(12):
        policy = {
            "stages": {"transport": 1},
            "arm_residual": {
                "applied_physics_steps": 100,
                "ik_update_accepts": 2,
                "ik_update_rejections": 0,
            },
        }
        if index in pretransport_failures:
            policy = {
                "stages": {},
                "arm_residual": {
                    "applied_physics_steps": 0,
                    "ik_update_accepts": 0,
                    "ik_update_rejections": 0,
                },
            }
        if not candidate:
            policy = {
                "stages": {"transport": 1},
                "arm_residual": {
                    "applied_physics_steps": 0,
                    "ik_update_accepts": 0,
                    "ik_update_rejections": 0,
                },
            }
        runs.append(
            {
                "episode_id": f"dev-{index}",
                "parameters": {"mass_kg": 0.3 + index / 100},
                "success": index not in failures,
                "placement_error_m": 0.015,
                "suction": {"max_contact_force_n": 10.0},
                "policy": policy,
            }
        )
    return {"status": "passed", "runs": runs}


def _holdout_audit(*, candidate: bool, failures: set[int] | None = None) -> dict:
    failures = failures or set()
    runs = []
    for index in range(100):
        arm = {
            "applied_physics_steps": 100 if candidate else 0,
            "ik_update_attempts": 2 if candidate else 0,
            "ik_update_accepts": 2 if candidate else 0,
            "ik_update_rejections": 0,
        }
        runs.append(
            {
                "episode_id": f"holdout-{index:03d}",
                "parameters": {"mass_kg": 0.3 + index / 1000},
                "success": index not in failures,
                "placement_error_m": 0.015 if not candidate else 0.016,
                "suction": {"max_contact_force_n": 10.0},
                "policy": {"stages": {"transport": 1}, "arm_residual": arm},
                "runtime": {
                    "rocm": "7.2.1",
                    "gpu_count": 1,
                    "gpu_name": "AMD Radeon Graphics",
                    "cuda": None,
                },
            }
        )
    return {"status": "passed", "runs": runs}


class MobileArmResidualAblationTests(unittest.TestCase):
    def test_authorizes_safe_non_regressing_arm_actuation(self) -> None:
        result = evaluate_arm_residual_development_gate(
            _audit(candidate=False), _audit(candidate=True)
        )
        self.assertTrue(result["closed_loop_holdout_authorized"])

    def test_rejects_baseline_success_regression(self) -> None:
        result = evaluate_arm_residual_development_gate(
            _audit(candidate=False), _audit(candidate=True, failures={3})
        )
        self.assertFalse(result["closed_loop_holdout_authorized"])
        self.assertEqual(result["paired_regressions"], ["dev-3"])

    def test_does_not_require_arm_actuation_before_transport(self) -> None:
        result = evaluate_arm_residual_development_gate(
            _audit(candidate=False, failures={5}),
            _audit(candidate=True, failures={5}, pretransport_failures={5}),
        )
        self.assertTrue(result["closed_loop_holdout_authorized"])
        self.assertEqual(result["arm_actuated_run_count"], 11)
        self.assertEqual(result["transport_eligible_run_count"], 11)

    def test_promotes_safe_noninferior_frozen_holdout(self) -> None:
        result = evaluate_arm_residual_holdout_gate(
            _holdout_audit(candidate=False, failures=set(range(5))),
            _holdout_audit(candidate=True, failures=set(range(6))),
        )
        self.assertTrue(result["promoted"])
        self.assertEqual(result["paired"]["candidate_regression"], 1)
        self.assertEqual(result["candidate"]["arm_ik_accepts"], 200)
        self.assertEqual(result["paired_statistics"]["mcnemar_exact_two_sided_p"], 1.0)
        self.assertAlmostEqual(
            result["paired_statistics"]["mean_placement_error_delta_m"], 0.001
        )

    def test_rejects_holdout_without_transport_arm_actuation(self) -> None:
        candidate = _holdout_audit(candidate=True, failures=set(range(5)))
        candidate["runs"][7]["policy"]["arm_residual"]["applied_physics_steps"] = 0
        result = evaluate_arm_residual_holdout_gate(
            _holdout_audit(candidate=False, failures=set(range(5))), candidate
        )
        self.assertFalse(result["promoted"])
        self.assertFalse(result["checks"]["arm_actuated_every_transport_run"])

    def test_rejects_holdout_below_target_success(self) -> None:
        result = evaluate_arm_residual_holdout_gate(
            _holdout_audit(candidate=False, failures=set(range(5))),
            _holdout_audit(candidate=True, failures=set(range(21))),
        )
        self.assertFalse(result["promoted"])
        self.assertFalse(result["checks"]["target_success_rate"])


if __name__ == "__main__":
    unittest.main()
