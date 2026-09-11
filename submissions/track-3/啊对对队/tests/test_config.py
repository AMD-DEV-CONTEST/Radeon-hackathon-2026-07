from dataclasses import replace
from pathlib import Path
import unittest

from parcel_sorter.config import load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_baseline_config_is_valid(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        self.assertEqual(config.simulation.backend, "rocm")
        self.assertEqual(config.simulation.device, "cuda:0")
        self.assertEqual(config.simulation.physics_hz, 240)
        self.assertEqual(config.simulation.control_hz, 30)
        self.assertEqual(config.simulation.camera_hz, 10)
        self.assertTrue(config.sensors.depth)
        self.assertTrue(config.randomization.enabled)
        self.assertFalse(config.task.grasp_planning_waypoint_collision_gate_enabled)
        self.assertFalse(
            config.task.grasp_planning_failed_candidate_blacklist_enabled
        )
        self.assertFalse(config.task.grasp_planning_reset_fallback_gate_enabled)
        self.assertFalse(config.task.grasp_planning_transport_contract_enabled)
        self.assertTrue(config.task.grasp_planning_transport_lookahead_enabled)
        self.assertFalse(config.task.parcel_gripper_adapter_enabled)
        self.assertEqual(config.task.parcel_gripper_adapter_extension_m, 0.030)
        self.assertEqual(config.task.parcel_gripper_adapter_density_kg_m3, 1240.0)
        self.assertTrue(config.task.parcel_gripper_adapter_inertia_enabled)
        self.assertFalse(config.control.transport_slip_recovery_enabled)
        self.assertFalse(config.control.transport_slip_setdown_regrasp_enabled)
        self.assertEqual(config.control.transport_slip_setdown_step_m, 0.010)
        self.assertEqual(config.control.transport_slip_setdown_max_steps, 20)
        self.assertEqual(config.control.transport_slip_force_boost_n, 2.0)
        self.assertEqual(len(config.control.arm_kp), 7)
        self.assertEqual(len(config.control.reset_qpos), 9)
        self.assertLessEqual(config.control.final_approach_step_m, config.control.max_ee_step_m)
        self.assertEqual(config.task.left_bin_center_m, (0.48, -0.34, 0.025))

    def test_final_approach_limit_cannot_exceed_global_limit(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(config.control, final_approach_step_m=0.05),
        )

        with self.assertRaisesRegex(ValueError, "final_approach_step_m"):
            invalid.validate()

    def test_parcel_gripper_extension_is_bounded(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        for extension_m in (0.0049, 0.0601):
            invalid = replace(
                config,
                task=replace(
                    config.task,
                    parcel_gripper_adapter_extension_m=extension_m,
                ),
            )
            with self.subTest(extension_m=extension_m):
                with self.assertRaisesRegex(
                    ValueError,
                    "parcel_gripper_adapter_extension_m",
                ):
                    invalid.validate()

    def test_parcel_gripper_density_is_bounded(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        for density_kg_m3 in (99.9, 2500.1):
            invalid = replace(
                config,
                task=replace(
                    config.task,
                    parcel_gripper_adapter_density_kg_m3=density_kg_m3,
                ),
            )
            with self.subTest(density_kg_m3=density_kg_m3):
                with self.assertRaisesRegex(
                    ValueError,
                    "parcel_gripper_adapter_density_kg_m3",
                ):
                    invalid.validate()

    def test_planned_final_approach_limit_cannot_exceed_global_limit(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            task=replace(
                config.task,
                grasp_planning_final_approach_step_m=(
                    config.control.max_ee_step_m + 0.001
                ),
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "grasp_planning_final_approach_step_m",
        ):
            invalid.validate()

    def test_tall_box_step_cannot_exceed_planned_approach_step(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            task=replace(
                config.task,
                grasp_planning_final_approach_step_m=0.005,
                grasp_planning_tall_box_final_approach_step_m=0.006,
            ),
        )

        with self.assertRaisesRegex(ValueError, "tall_box_final_approach_step_m"):
            invalid.validate()

    def test_planned_transport_step_cannot_exceed_global_limit(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            task=replace(
                config.task,
                grasp_planning_transport_step_m=(
                    config.control.max_ee_step_m + 0.001
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "grasp_planning_transport_step_m"):
            invalid.validate()

    def test_transport_slip_recovery_requires_transport_contract(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(config.control, transport_slip_recovery_enabled=True),
        )

        with self.assertRaisesRegex(ValueError, "transport_slip_recovery_enabled"):
            invalid.validate()

    def test_failed_candidate_blacklist_requires_retry_replanning(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            task=replace(
                config.task,
                grasp_planning_retry_replan_enabled=False,
                grasp_planning_failed_candidate_blacklist_enabled=True,
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "grasp_planning_failed_candidate_blacklist_enabled",
        ):
            invalid.validate()

    def test_disabling_transport_lookahead_requires_transport_contract(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            task=replace(
                config.task,
                grasp_planning_transport_lookahead_enabled=False,
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "grasp_planning_transport_lookahead_enabled",
        ):
            invalid.validate()

    def test_transport_slip_setdown_requires_transport_contract(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(
                config.control,
                transport_slip_setdown_regrasp_enabled=True,
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "transport_slip_setdown_regrasp_enabled",
        ):
            invalid.validate()

    def test_transport_slip_setdown_motion_is_bounded(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid_step = replace(
            config,
            control=replace(
                config.control,
                transport_slip_setdown_step_m=(
                    config.control.max_ee_step_m + 0.001
                ),
            ),
        )
        invalid_steps = replace(
            config,
            control=replace(
                config.control,
                transport_slip_setdown_max_steps=0,
            ),
        )

        with self.assertRaisesRegex(ValueError, "transport_slip_setdown_step_m"):
            invalid_step.validate()
        with self.assertRaisesRegex(ValueError, "transport_slip_setdown_max_steps"):
            invalid_steps.validate()

    def test_transport_slip_force_target_preserves_safety_margin(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            task=replace(
                config.task,
                grasp_planning_transport_contract_enabled=True,
            ),
            control=replace(
                config.control,
                transport_slip_recovery_enabled=True,
                transport_slip_force_boost_n=5.1,
            ),
        )

        with self.assertRaisesRegex(ValueError, "at least 10 N below"):
            invalid.validate()

    def test_reset_fallback_gate_requires_planning_and_collision_checked_reset(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        without_planner = replace(
            config,
            task=replace(
                config.task,
                grasp_planning_reset_fallback_gate_enabled=True,
            ),
            control=replace(config.control, collision_checked_reset_enabled=True),
        )
        with self.assertRaisesRegex(ValueError, "geometry_aware_grasp_planning_enabled"):
            without_planner.validate()

        without_collision_check = replace(
            config,
            task=replace(
                config.task,
                geometry_aware_grasp_planning_enabled=True,
                grasp_planning_reset_fallback_gate_enabled=True,
            ),
        )
        with self.assertRaisesRegex(ValueError, "collision_checked_reset_enabled"):
            without_collision_check.validate()

    def test_approach_step_cannot_exceed_global_limit(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(config.control, approach_step_m=0.05),
        )

        with self.assertRaisesRegex(ValueError, "approach_step_m"):
            invalid.validate()

    def test_approach_contact_brake_threshold_stays_below_safety_limit(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(config.control, approach_contact_brake_force_n=35.0),
        )

        with self.assertRaisesRegex(ValueError, "approach_contact_brake_force_n"):
            invalid.validate()

    def test_approach_barrier_recovery_step_is_bounded(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(
                config.control,
                approach_barrier_recovery_step_m=config.control.max_ee_step_m * 4.01,
            ),
        )

        with self.assertRaisesRegex(ValueError, "approach_barrier_recovery_step_m"):
            invalid.validate()

    def test_precontact_aabb_guard_distance_is_bounded(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(
                config.control,
                precontact_aabb_guard_distance_m=config.control.max_ee_step_m * 4.01,
            ),
        )

        with self.assertRaisesRegex(ValueError, "precontact_aabb_guard_distance_m"):
            invalid.validate()

    def test_approach_stiffness_scale_is_at_most_one(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(config.control, approach_stiffness_scale=1.01),
        )

        with self.assertRaisesRegex(ValueError, "approach_stiffness_scale"):
            invalid.validate()

    def test_approach_velocity_parameters_are_positive_and_bounded(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(config.control, approach_velocity_damping=1.01),
        )

        with self.assertRaisesRegex(ValueError, "approach_velocity_damping"):
            invalid.validate()
        invalid_weight = replace(
            config,
            control=replace(config.control, approach_velocity_orientation_weight=1.01),
        )
        with self.assertRaisesRegex(ValueError, "orientation_weight"):
            invalid_weight.validate()

    def test_collision_free_reset_pose_requires_nine_finite_values(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            control=replace(config.control, collision_free_reset_qpos=(0.0,) * 8),
        )

        with self.assertRaisesRegex(ValueError, "collision_free_reset_qpos"):
            invalid.validate()

    def test_surface_aware_pregrasp_parameters_must_be_positive(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            task=replace(
                config.task,
                surface_aware_pregrasp_min_side_overlap_m=0.0,
            ),
        )

        with self.assertRaisesRegex(ValueError, "min_side_overlap"):
            invalid.validate()

        invalid_height = replace(
            config,
            task=replace(
                config.task,
                surface_aware_pregrasp_min_height_m=0.0,
            ),
        )
        with self.assertRaisesRegex(ValueError, "min_height"):
            invalid_height.validate()

    def test_parcel_profile_rejects_negative_rolling_friction(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "catalog_v2.toml")
        invalid_profile = replace(config.parcel_profiles[0], rolling_friction=-0.001)
        invalid = replace(
            config,
            parcel_profiles=(invalid_profile, *config.parcel_profiles[1:]),
        )

        with self.assertRaisesRegex(ValueError, "rolling_friction"):
            invalid.validate()

    def test_reset_pose_requires_nine_finite_values(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(config, control=replace(config.control, reset_qpos=(0.0,) * 8))

        with self.assertRaisesRegex(ValueError, "reset_qpos"):
            invalid.validate()

    def test_approach_clearance_margin_must_be_non_negative(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            task=replace(config.task, approach_clearance_margin_m=-0.001),
        )

        with self.assertRaisesRegex(ValueError, "approach_clearance_margin_m"):
            invalid.validate()

    def test_retry_retreat_distance_must_be_non_negative(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        invalid = replace(
            config,
            task=replace(config.task, retry_retreat_distance_m=-0.001),
        )

        with self.assertRaisesRegex(ValueError, "retry_retreat_distance_m"):
            invalid.validate()


if __name__ == "__main__":
    unittest.main()
