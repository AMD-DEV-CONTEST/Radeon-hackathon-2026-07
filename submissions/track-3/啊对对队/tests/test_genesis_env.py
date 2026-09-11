import math
import unittest
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import numpy as np

from parcel_sorter.config import load_config
from parcel_sorter.contracts import CartesianAction, RobotState
from parcel_sorter.genesis_env import (
    GenesisParcelEnv,
    aabb_gap_m,
    build_parcel_gripper_mjcf,
    cartesian_velocity_twist,
    combine_rigid_body_with_box_inertia,
    cross_entity_collision_pairs,
    damped_least_squares_velocity,
    detect_transport_slip,
    genesis_depth_to_meters,
    resolve_geometry_grasp_planning_active,
    scaled_robot_gains,
    wrist_camera_pose,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WristCameraPoseTests(unittest.TestCase):
    def test_tracks_panda_hand_frame(self) -> None:
        position, lookat, up = wrist_camera_pose(
            (1.0, 2.0, 3.0), (1.0, 0.0, 0.0, 0.0), np
        )
        np.testing.assert_allclose(position, (1.0, 2.02, 2.955))
        np.testing.assert_allclose(lookat, (1.0, 2.0, 3.18))
        np.testing.assert_allclose(up, (0.0, 1.0, 0.0))


class ParcelGripperAssetTests(unittest.TestCase):
    def test_generates_symmetric_collision_and_visual_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assets").mkdir()
            source = root / "panda.xml"
            source.write_text(
                """<mujoco><compiler meshdir="assets"/><worldbody><body name="hand">
<body name="left_finger"><inertial mass="0.015" pos="0 0 0" diaginertia="2.375e-6 2.375e-6 7.5e-7"/></body>
<body name="right_finger"><inertial mass="0.015" pos="0 0 0" diaginertia="2.375e-6 2.375e-6 7.5e-7"/></body>
</body></worldbody></mujoco>""",
                encoding="utf-8",
            )
            output = root / "generated" / "panda_adapter.xml"

            result = build_parcel_gripper_mjcf(source, output, 0.030)

            self.assertEqual(result, output.resolve())
            generated = ET.parse(output).getroot()
            compiler = generated.find("compiler")
            self.assertEqual(compiler.attrib["meshdir"], str((root / "assets").resolve()))
            for finger_name in ("left_finger", "right_finger"):
                finger = generated.find(f".//body[@name='{finger_name}']")
                collision = finger.find(
                    f"geom[@name='{finger_name}_parcel_adapter_collision']"
                )
                visual = finger.find(
                    f"geom[@name='{finger_name}_parcel_adapter_visual']"
                )
                self.assertEqual(collision.attrib["type"], "box")
                self.assertEqual(collision.attrib["size"], "0.010 0.004 0.015000000")
                self.assertEqual(collision.attrib["pos"], "0 0.0055 0.068000000")
                self.assertEqual(visual.attrib["contype"], "0")
                self.assertEqual(visual.attrib["conaffinity"], "0")
                inertial = finger.find("inertial")
                self.assertAlmostEqual(float(inertial.attrib["mass"]), 0.020952)
                self.assertNotIn("diaginertia", inertial.attrib)
                self.assertEqual(len(inertial.attrib["fullinertia"].split()), 6)

            stock_output = root / "generated" / "panda_adapter_stock_inertia.xml"
            build_parcel_gripper_mjcf(
                source,
                stock_output,
                0.030,
                combine_adapter_inertia=False,
            )
            stock_inertial = ET.parse(stock_output).getroot().find(
                ".//body[@name='left_finger']/inertial"
            )
            self.assertEqual(stock_inertial.attrib["mass"], "0.015")
            self.assertIn("diaginertia", stock_inertial.attrib)
            self.assertNotIn("fullinertia", stock_inertial.attrib)

    def test_rejects_unbounded_extension_before_reading_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "extension"):
            build_parcel_gripper_mjcf("missing.xml", "output.xml", 0.061)

    def test_combines_box_mass_center_and_parallel_axis_inertia(self) -> None:
        mass, center, full_inertia = combine_rigid_body_with_box_inertia(
            0.015,
            (0.0, 0.0, 0.0),
            (2.375e-6, 2.375e-6, 7.5e-7, 0.0, 0.0, 0.0),
            1240.0,
            (0.010, 0.004, 0.015),
            (0.0, 0.0055, 0.068),
        )

        self.assertAlmostEqual(mass, 0.020952)
        self.assertAlmostEqual(center[0], 0.0)
        self.assertAlmostEqual(center[1], 0.00156242840778923)
        self.assertAlmostEqual(center[2], 0.0193172966781214)
        self.assertTrue(all(math.isfinite(value) for value in full_inertia))
        self.assertGreater(full_inertia[0], 2.375e-6)
        self.assertLess(full_inertia[5], 0.0)
        ixx, iyy, izz, ixy, ixz, iyz = full_inertia
        self.assertGreater(ixx, 0.0)
        self.assertGreater(ixx * iyy - ixy * ixy, 0.0)
        determinant = (
            ixx * (iyy * izz - iyz * iyz)
            - ixy * (ixy * izz - iyz * ixz)
            + ixz * (ixy * iyz - iyy * ixz)
        )
        self.assertGreater(determinant, 0.0)


class DiagnosticGraspAllowlistTests(unittest.TestCase):
    def _environment(self) -> GenesisParcelEnv:
        env = GenesisParcelEnv.__new__(GenesisParcelEnv)
        env._grasp_plan_attempts = 0
        env.control_step = 0
        env._diagnostic_grasp_candidate_allowlist = None
        return env

    def test_freezes_nonempty_allowlist_before_execution(self) -> None:
        env = self._environment()

        env.set_diagnostic_grasp_candidate_allowlist(frozenset({"candidate-b", "candidate-a"}))

        self.assertEqual(
            env._diagnostic_grasp_candidate_allowlist,
            frozenset({"candidate-a", "candidate-b"}),
        )

    def test_rejects_empty_or_late_allowlist(self) -> None:
        env = self._environment()
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            env.set_diagnostic_grasp_candidate_allowlist(frozenset())

        env._grasp_plan_attempts = 1
        with self.assertRaisesRegex(RuntimeError, "before execution"):
            env.set_diagnostic_grasp_candidate_allowlist(frozenset({"candidate-a"}))


class GenesisDepthTests(unittest.TestCase):
    def test_preserves_genesis_depth_in_meters(self) -> None:
        raw_depth_m = np.asarray([[0.8, 3.4185]], dtype=np.float32)

        depth_m = genesis_depth_to_meters(raw_depth_m, np)

        np.testing.assert_allclose(depth_m, [[0.8, 3.4185]], rtol=1e-6)
        self.assertEqual(depth_m.dtype, np.float32)


class AabbGapTests(unittest.TestCase):
    def test_separated_boxes_use_euclidean_axis_gap(self) -> None:
        first = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        second = ((2.0, 3.0, 1.0), (3.0, 4.0, 2.0))

        self.assertAlmostEqual(aabb_gap_m(first, second), np.sqrt(5.0))

    def test_overlapping_boxes_have_zero_gap(self) -> None:
        first = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        second = ((0.5, -1.0, 0.2), (2.0, 0.5, 0.8))

        self.assertEqual(aabb_gap_m(first, second), 0.0)

    def test_rejects_malformed_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "min and max"):
            aabb_gap_m(((0.0, 0.0, 0.0),), ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)))


class TransportSlipDetectionTests(unittest.TestCase):
    @staticmethod
    def _state(
        *,
        end_effector_position: tuple[float, float, float],
        parcel_position: tuple[float, float, float],
        force_n: float,
        destination: tuple[float, float, float] = (0.48, 0.34, 0.025),
    ) -> RobotState:
        return RobotState(
            joint_positions=(0.0,) * 9,
            end_effector_pose=(*end_effector_position, 1.0, 0.0, 0.0, 0.0),
            parcel_pose=(*parcel_position, 1.0, 0.0, 0.0, 0.0),
            target_position=destination,
            gripper_contact_force_n=force_n,
        )

    def test_triggers_on_mid_transfer_downward_relative_jump(self) -> None:
        state = self._state(
            end_effector_position=(0.596, 0.024, 0.335),
            parcel_position=(0.585, 0.030, 0.168),
            force_n=16.52,
        )

        signal = detect_transport_slip(
            (0.0057, -0.0030, 0.1560),
            state,
            phase="transfer",
            relative_delta_threshold_m=0.008,
            downward_delta_threshold_m=0.006,
            min_contact_force_n=1.0,
            min_destination_distance_m=0.080,
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertTrue(signal.triggered)
        self.assertGreater(signal.relative_delta_m, 0.008)
        self.assertGreater(signal.downward_delta_m, 0.006)
        self.assertGreater(signal.destination_distance_m, 0.080)

    def test_excludes_equivalent_jump_at_destination(self) -> None:
        state = self._state(
            end_effector_position=(0.480, 0.335, 0.352),
            parcel_position=(0.463, 0.343, 0.159),
            force_n=13.88,
        )

        signal = detect_transport_slip(
            (0.011, 0.003, 0.176),
            state,
            phase="transfer",
            relative_delta_threshold_m=0.008,
            downward_delta_threshold_m=0.006,
            min_contact_force_n=1.0,
            min_destination_distance_m=0.080,
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertGreater(signal.relative_delta_m, 0.008)
        self.assertFalse(signal.triggered)
        self.assertLess(signal.destination_distance_m, 0.080)

    def test_requires_active_phase_downward_motion_and_contact(self) -> None:
        base = self._state(
            end_effector_position=(0.600, 0.020, 0.340),
            parcel_position=(0.590, 0.020, 0.170),
            force_n=5.0,
        )
        cases = (
            ("descend", base, (0.0, 0.0, 0.150)),
            (
                "transfer",
                replace(base, gripper_contact_force_n=0.0),
                (0.0, 0.0, 0.150),
            ),
            ("transfer", base, (0.0, 0.0, 0.169)),
        )

        for phase, state, previous in cases:
            with self.subTest(phase=phase, force=state.gripper_contact_force_n):
                signal = detect_transport_slip(
                    previous,
                    state,
                    phase=phase,
                    relative_delta_threshold_m=0.008,
                    downward_delta_threshold_m=0.006,
                    min_contact_force_n=1.0,
                    min_destination_distance_m=0.080,
                )
                self.assertIsNotNone(signal)
                assert signal is not None
                self.assertFalse(signal.triggered)


class PrecontactAabbGuardTests(unittest.TestCase):
    def _environment(
        self,
        end_effector_position: tuple[float, float, float],
        parcel_position: tuple[float, float, float],
    ) -> GenesisParcelEnv:
        env = GenesisParcelEnv.__new__(GenesisParcelEnv)
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        env.config = replace(
            config,
            control=replace(config.control, precontact_aabb_guard_distance_m=0.04),
        )
        env.end_effector = SimpleNamespace(
            get_pos=lambda: np.asarray(end_effector_position, dtype=np.float32)
        )
        env.parcel = SimpleNamespace(
            get_pos=lambda: np.asarray(parcel_position, dtype=np.float32)
        )
        env.expert = SimpleNamespace(approach_clearance_m=lambda: 0.26)
        env._finger_parcel_aabb_gap_m = lambda: 0.01
        env._aabb_guard_filter_count = 0
        env._aabb_guard_active_steps = 0
        env._aabb_guard_max_active_steps = 0
        env._aabb_guard_samples = 0
        env._aabb_guard_compute_ms_total = 0.0
        env._aabb_guard_last_gap_m = None
        env._aabb_guard_last_compute_ms = 0.0
        env._aabb_guard_last_triggered = False
        env._aabb_guard_last_reason = None
        env._aabb_guard_last_nominal_target_m = None
        env._aabb_guard_last_filtered_target_m = None
        return env

    def test_filters_horizontal_approach_into_vertical_recovery(self) -> None:
        env = self._environment((0.30, 0.0, 0.10), (0.60, 0.0, 0.05))
        action = CartesianAction(
            target_position=(0.34, 0.0, 0.10),
            target_quaternion=(0.0, 1.0, 0.0, 0.0),
            gripper=1.0,
            command="move_pregrasp",
        )

        filtered = env._filter_precontact_action(action)

        self.assertAlmostEqual(filtered.target_position[0], 0.30, places=6)
        self.assertGreater(filtered.target_position[2], 0.10)
        self.assertEqual(env._aabb_guard_filter_count, 1)
        self.assertEqual(env._aabb_guard_last_reason, "raise_to_transit")

    def test_does_not_filter_inside_final_descent_window(self) -> None:
        env = self._environment((0.59, 0.0, 0.20), (0.60, 0.0, 0.05))
        action = CartesianAction(
            target_position=(0.60, 0.0, 0.18),
            target_quaternion=(0.0, 1.0, 0.0, 0.0),
            gripper=1.0,
            command="move_pregrasp",
        )

        filtered = env._filter_precontact_action(action)

        self.assertEqual(filtered, action)
        self.assertEqual(env._aabb_guard_filter_count, 0)


class ApproachComplianceTests(unittest.TestCase):
    def test_scales_only_arm_gains_and_preserves_damping_relationship(self) -> None:
        kp, kv = scaled_robot_gains(
            (400.0,) * 7,
            (40.0,) * 7,
            100.0,
            10.0,
            0.25,
        )

        self.assertEqual(kp[:7], (100.0,) * 7)
        self.assertEqual(kv[:7], (20.0,) * 7)
        self.assertEqual(kp[7:], (100.0, 100.0))
        self.assertEqual(kv[7:], (10.0, 10.0))

    def test_switches_gains_only_on_command_transition(self) -> None:
        class FakeRobot:
            def __init__(self) -> None:
                self.kp_calls: list[np.ndarray] = []
                self.kv_calls: list[np.ndarray] = []

            def set_dofs_kp(self, gains: np.ndarray) -> None:
                self.kp_calls.append(gains.copy())

            def set_dofs_kv(self, gains: np.ndarray) -> None:
                self.kv_calls.append(gains.copy())

        env = GenesisParcelEnv.__new__(GenesisParcelEnv)
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        env.config = replace(
            config,
            control=replace(config.control, approach_stiffness_scale=0.5),
        )
        env.robot = FakeRobot()
        env.np = np
        env._active_arm_stiffness_scale = 1.0

        env._set_arm_stiffness_for_command("move_pregrasp")
        self.assertEqual(len(env.robot.kp_calls), 1)
        self.assertEqual(len(env.robot.kv_calls), 1)
        np.testing.assert_allclose(
            env.robot.kp_calls[-1][:7], np.asarray(config.control.arm_kp) * 0.5
        )
        np.testing.assert_allclose(
            env.robot.kv_calls[-1][:7], np.asarray(config.control.arm_kv) * np.sqrt(0.5)
        )

        env._set_arm_stiffness_for_command("move_pregrasp")
        self.assertEqual(len(env.robot.kp_calls), 1)

        env._set_arm_stiffness_for_command("grasp")
        self.assertEqual(len(env.robot.kp_calls), 2)
        np.testing.assert_allclose(env.robot.kp_calls[-1][:7], np.asarray(config.control.arm_kp))


class ApproachVelocityControlTests(unittest.TestCase):
    def test_cartesian_twist_uses_shortest_quaternion_arc_and_limits_speed(self) -> None:
        twist = cartesian_velocity_twist(
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (-1.0, 0.0, 0.0, 0.0),
            position_gain_s=8.0,
            orientation_gain_s=6.0,
            max_linear_m_s=0.3,
            max_angular_rad_s=1.5,
        )

        np.testing.assert_allclose(twist[:3], (0.3, 0.0, 0.0), atol=1e-9)
        np.testing.assert_allclose(twist[3:], (0.0, 0.0, 0.0), atol=1e-9)

    def test_damped_least_squares_tracks_identity_and_clamps_joint_speed(self) -> None:
        jacobian = np.eye(6, dtype=np.float64)
        twist = np.asarray((2.0, -1.0, 0.5, 0.0, 0.0, 0.0))

        velocity = damped_least_squares_velocity(
            jacobian,
            twist,
            damping=0.05,
            max_joint_velocity=1.0,
            array_module=np,
        )

        self.assertAlmostEqual(float(np.max(np.abs(velocity))), 1.0)
        self.assertGreater(velocity[0], 0.0)
        self.assertLess(velocity[1], 0.0)


class CollisionCheckedResetTests(unittest.TestCase):
    def test_filters_and_canonicalizes_cross_entity_collision_pairs(self) -> None:
        pairs = np.asarray(((1, 2), (12, 21), (22, 11), (12, 21), (13, 14), (21, 22)))

        result = cross_entity_collision_pairs(pairs, (10, 20), (20, 30))

        self.assertEqual(result, ((12, 21), (11, 22)))

    def test_reset_fallback_gate_activates_planner_only_for_observed_risk(self) -> None:
        cases = (
            (False, True, True, True, False),
            (True, False, True, True, False),
            (True, True, False, False, True),
            (True, True, True, False, False),
            (True, True, True, True, True),
        )
        for enabled, eligible, gate, fallback_used, expected in cases:
            with self.subTest(
                enabled=enabled,
                eligible=eligible,
                gate=gate,
                fallback_used=fallback_used,
            ):
                self.assertEqual(
                    resolve_geometry_grasp_planning_active(
                        planning_enabled=enabled,
                        geometry_eligible=eligible,
                        reset_fallback_gate_enabled=gate,
                        reset_fallback_used=fallback_used,
                    ),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
