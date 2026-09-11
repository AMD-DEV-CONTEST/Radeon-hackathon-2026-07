import unittest

from parcel_sorter.comparison import compare_expert_runs


def _run(successes: tuple[bool, ...], forces: tuple[float, ...]) -> dict:
    episodes = [
        {
            "episode_index": index,
            "sample": {"episode_index": index, "mass_kg": 0.5 + index * 0.1},
            "result": {
                "success": success,
                "max_contact_force_n": force,
            },
        }
        for index, (success, force) in enumerate(zip(successes, forces, strict=True))
    ]
    successful = sum(successes)
    return {
        "config": {"task": {"max_contact_force_n": 35.0}},
        "summary": {
            "success_rate": successful / len(episodes),
            "drop_rate": 0.0,
            "successful_parcels_per_hour": successful * 100.0,
        },
        "episodes": episodes,
    }


class ExpertComparisonTests(unittest.TestCase):
    def test_same_episode_comparison_reports_recovery_and_force_aborts(self) -> None:
        baseline = _run((False, True), (50.0, 20.0))
        candidate = _run((True, True), (20.0, 18.0))

        result = compare_expert_runs(baseline, candidate)

        self.assertEqual(result["recovered_episode_indices"], [0])
        self.assertEqual(result["regressed_episode_indices"], [])
        self.assertEqual(result["baseline_force_abort_indices"], [0])
        self.assertEqual(result["candidate_force_abort_indices"], [])
        self.assertEqual(result["recommendation"], "keep")

    def test_mismatched_episode_sets_are_rejected(self) -> None:
        baseline = _run((True, True), (10.0, 10.0))
        candidate = _run((True,), (10.0,))

        with self.assertRaisesRegex(ValueError, "episode sets differ"):
            compare_expert_runs(baseline, candidate)

    def test_mismatched_randomization_sample_is_rejected(self) -> None:
        baseline = _run((True,), (10.0,))
        candidate = _run((True,), (10.0,))
        candidate["episodes"][0]["sample"]["mass_kg"] = 0.9

        with self.assertRaisesRegex(ValueError, "randomization samples differ"):
            compare_expert_runs(baseline, candidate)

    def test_mismatched_safety_threshold_is_rejected(self) -> None:
        baseline = _run((True,), (10.0,))
        candidate = _run((True,), (10.0,))
        candidate["config"]["task"]["max_contact_force_n"] = 40.0

        with self.assertRaisesRegex(ValueError, "thresholds differ"):
            compare_expert_runs(baseline, candidate)

    def test_config_difference_contract_requires_exact_paths(self) -> None:
        baseline = _run((True,), (10.0,))
        candidate = _run((True,), (10.0,))
        baseline["config"]["control"] = {"reset_qpos": [0.0, 1.0]}
        candidate["config"]["control"] = {"reset_qpos": [0.5, 1.0]}

        result = compare_expert_runs(
            baseline,
            candidate,
            allowed_config_differences=("control.reset_qpos",),
        )
        self.assertEqual(result["config_difference_paths"], ["control.reset_qpos"])

        candidate["config"]["task"]["episode_seconds"] = 30.0
        with self.assertRaisesRegex(ValueError, "unexpected=.*task.episode_seconds"):
            compare_expert_runs(
                baseline,
                candidate,
                allowed_config_differences=("control.reset_qpos",),
            )

    def test_aggregates_optional_precontact_aabb_telemetry(self) -> None:
        baseline = _run((True, True), (10.0, 10.0))
        candidate = _run((True, True), (10.0, 10.0))
        for index, episode in enumerate(candidate["episodes"]):
            episode["safety_summary"] = {
                "precontact_aabb_guard_enabled": True,
                "precontact_aabb_guard_filter_count": index + 1,
                "precontact_aabb_guard_max_active_steps": 2 + index,
                "precontact_aabb_guard_samples": 10,
                "precontact_aabb_guard_compute_ms_total": 15.0,
            }

        result = compare_expert_runs(baseline, candidate)

        self.assertFalse(result["baseline_precontact_aabb_guard"]["enabled"])
        self.assertTrue(result["candidate_precontact_aabb_guard"]["enabled"])
        self.assertEqual(result["candidate_precontact_aabb_guard"]["filter_count"], 3)
        self.assertEqual(result["candidate_precontact_aabb_guard"]["max_active_steps"], 3)
        self.assertEqual(result["candidate_precontact_aabb_guard"]["samples"], 20)
        self.assertAlmostEqual(
            result["candidate_precontact_aabb_guard"]["compute_ms_mean"],
            1.5,
        )

    def test_aggregates_optional_approach_velocity_telemetry(self) -> None:
        baseline = _run((True, True), (10.0, 10.0))
        candidate = _run((True, True), (10.0, 10.0))
        for index, episode in enumerate(candidate["episodes"]):
            episode["safety_summary"] = {
                "approach_velocity_control_enabled": True,
                "approach_velocity_control_samples": 10,
                "approach_velocity_control_compute_ms_total": 12.0,
                "approach_velocity_control_max_joint_rad_s": 1.0 + index * 0.2,
                "approach_velocity_control_max_pose_error_m": 0.04 + index * 0.01,
            }

        result = compare_expert_runs(baseline, candidate)

        self.assertFalse(result["baseline_approach_velocity_control"]["enabled"])
        summary = result["candidate_approach_velocity_control"]
        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["samples"], 20)
        self.assertAlmostEqual(summary["compute_ms_mean"], 1.2)
        self.assertAlmostEqual(summary["max_joint_command_rad_s"], 1.2)
        self.assertAlmostEqual(summary["max_pose_error_m"], 0.05)

    def test_aggregates_collision_checked_reset_telemetry(self) -> None:
        baseline = _run((True, True), (10.0, 10.0))
        candidate = _run((True, True), (10.0, 10.0))
        for index, episode in enumerate(candidate["episodes"]):
            episode["safety_summary"] = {
                "collision_checked_reset_enabled": True,
                "collision_checked_reset_used": index == 0,
                "collision_checked_reset_compute_ms": 2.0 + index,
                "initial_robot_parcel_collisions": [{"robot_link": "hand"}],
                "fallback_robot_parcel_collisions": [],
            }

        result = compare_expert_runs(baseline, candidate)

        self.assertFalse(result["baseline_collision_checked_reset"]["enabled"])
        summary = result["candidate_collision_checked_reset"]
        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["episodes_checked"], 2)
        self.assertEqual(summary["fallback_episodes"], 1)
        self.assertEqual(summary["initial_collision_pairs"], 2)
        self.assertEqual(summary["fallback_collision_pairs"], 0)
        self.assertAlmostEqual(summary["compute_ms_mean"], 2.5)

    def test_aggregates_reset_gated_grasp_planning_telemetry(self) -> None:
        baseline = _run((True, True), (10.0, 10.0))
        candidate = _run((True, True), (10.0, 10.0))
        candidate["episodes"][0]["safety_summary"] = {
            "geometry_aware_grasp_planning_enabled": True,
            "geometry_aware_grasp_planning_geometry_eligible": True,
            "grasp_planning_reset_fallback_gate_enabled": True,
            "grasp_planning_reset_fallback_gate_satisfied": True,
            "geometry_aware_grasp_planning_active": True,
            "grasp_plan_attempts": 2,
            "grasp_plan_compute_ms_total": 12.0,
        }
        candidate["episodes"][1]["safety_summary"] = {
            "geometry_aware_grasp_planning_enabled": True,
            "geometry_aware_grasp_planning_geometry_eligible": True,
            "grasp_planning_reset_fallback_gate_enabled": True,
            "grasp_planning_reset_fallback_gate_satisfied": False,
            "geometry_aware_grasp_planning_active": False,
            "grasp_plan_attempts": 0,
            "grasp_plan_compute_ms_total": 0.0,
        }

        result = compare_expert_runs(baseline, candidate)

        self.assertFalse(result["baseline_grasp_planning"]["configured"])
        summary = result["candidate_grasp_planning"]
        self.assertTrue(summary["configured"])
        self.assertTrue(summary["reset_fallback_gate_enabled"])
        self.assertEqual(summary["geometry_eligible_episodes"], 2)
        self.assertEqual(summary["gate_satisfied_episodes"], 1)
        self.assertEqual(summary["active_episodes"], 1)
        self.assertEqual(summary["gate_avoided_episodes"], 1)
        self.assertEqual(summary["attempts"], 2)
        self.assertAlmostEqual(summary["compute_ms_per_attempt"], 6.0)


if __name__ == "__main__":
    unittest.main()
