import contextlib
import importlib
import io
import math
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np


fake_genesis_env = types.ModuleType("simulation.genesis_env")
fake_genesis_env.BASKET_HOME = (0.24, 0.1)
fake_genesis_env.BASKET_SIZE = (0.1, 0.1, 0.06)
fake_genesis_env.CUBE_SIZE = 0.03
fake_genesis_env.TABLE_TOP_Z = 0.75
missing_module = object()
previous_genesis_env = sys.modules.get("simulation.genesis_env", missing_module)
try:
    sys.modules["simulation.genesis_env"] = fake_genesis_env
    scripted_pick = importlib.import_module("simulation.scripted_pick")
finally:
    if previous_genesis_env is missing_module:
        sys.modules.pop("simulation.genesis_env", None)
    else:
        sys.modules["simulation.genesis_env"] = previous_genesis_env


class FakeGeom:
    def __init__(self, idx, *, n_verts=8, contype=1, conaffinity=1):
        self.idx = idx
        self.n_verts = n_verts
        self.contype = contype
        self.conaffinity = conaffinity


class FakeLink:
    def __init__(
        self,
        pos=(0.0, 0.0, 0.0),
        quat=(1.0, 0.0, 0.0, 0.0),
        idx=None,
        geoms=None,
    ):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.quat = np.asarray(quat, dtype=np.float64)
        self.idx = idx
        self.geoms = list(geoms or [])

    def get_pos(self):
        return self.pos.copy()

    def get_quat(self):
        return self.quat.copy()


class TorchLikeTensor:
    def __init__(self, value):
        self.value = np.asarray(value, dtype=np.float64)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.value.copy()

    def __array__(self, *args, **kwargs):
        raise TypeError("direct np.asarray conversion is not supported")


class FakeRobot:
    def __init__(self, qpos=None, *, links=None, contacts=None):
        self.qpos = np.asarray(
            qpos
            if qpos is not None
            else [0.0, 0.0, 0.0, math.pi / 2, math.pi / 2, 1.7],
            dtype=np.float64,
        )
        self.links = (
            links
            if links is not None
            else {
                "gripper": FakeLink(
                    idx=10,
                    geoms=[
                        FakeGeom(24, n_verts=252),
                        FakeGeom(25, n_verts=775),
                        FakeGeom(26),
                    ],
                ),
                "moving_jaw_so101_v1": FakeLink(idx=20, geoms=[FakeGeom(27)]),
            }
        )
        self.contacts = list(contacts or [])
        self.contact_queries = []
        self.commands = []

    def get_qpos(self):
        return self.qpos.copy()

    def get_dofs_position(self, indices):
        return self.qpos[np.asarray(indices)]

    def get_link(self, name):
        return self.links[name]

    def get_contacts(self, *, with_entity):
        self.contact_queries.append(with_entity)
        return self.contacts.pop(0) if self.contacts else {}

    def control_dofs_position(self, values, indices):
        values = np.asarray(values, dtype=np.float64)
        indices = np.asarray(indices)
        self.commands.append(values.copy())
        self.qpos[indices] = values


def make_picker(*, robot=None, link=None, cube_pos=(0.2, 0.0, 0.77)):
    robot = robot or FakeRobot()
    link = link or FakeLink()
    cube = SimpleNamespace(get_pos=mock.Mock(return_value=np.asarray(cube_pos)))
    bundle = SimpleNamespace(
        robot=robot,
        _ee_link=link,
        cubes={"red": cube},
        scene=SimpleNamespace(step=mock.Mock()),
        update_wrist_cam=mock.Mock(),
    )
    return scripted_pick.ScriptedPickPlace(bundle)


def motion_result(converged, *, arm_goal=None, target_tip=None):
    return scripted_pick.MotionResult(
        converged=converged,
        arm_goal=np.asarray(arm_goal if arm_goal is not None else np.zeros(5)),
        target_tip=np.asarray(target_tip if target_tip is not None else np.zeros(3)),
        actual_tip=np.zeros(3),
        error_vector=np.zeros(3),
        tcp_error=0.0,
        ik_error=0.0,
        joint_error=0.0,
        interp_steps=30,
        settle_steps=5,
    )


def pad_contact(*geom_indices, force=1.0):
    return {
        "geom_a": np.asarray(geom_indices),
        "geom_b": np.full(len(geom_indices), 99),
        "link_a": np.asarray([19 if geom != 27 else 20 for geom in geom_indices]),
        "link_b": np.full(len(geom_indices), 99),
        "force_a": np.asarray([[force, 0.0, 0.0]] * len(geom_indices)),
    }


class TipPositionTests(unittest.TestCase):
    def test_tip_pos_rotates_link_local_offset(self):
        link = FakeLink(
            pos=[1.0, 2.0, 3.0],
            quat=[math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0],
        )
        picker = make_picker(link=link)

        np.testing.assert_allclose(picker._tip_pos(), [0.902, 2.0, 3.0], atol=1e-12)

    def test_tip_pos_normalizes_torch_like_link_state_before_geometry(self):
        link = SimpleNamespace(
            get_pos=lambda: TorchLikeTensor([1.0, 2.0, 3.0]),
            get_quat=lambda: TorchLikeTensor(
                [math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0]
            ),
        )
        picker = make_picker(link=link)

        np.testing.assert_allclose(picker._tip_pos(), [0.902, 2.0, 3.0], atol=1e-12)


class RunConvergenceGateTests(unittest.TestCase):
    def test_run_aborts_before_close_when_pregrasp_does_not_converge(self):
        picker = make_picker()
        picker._move_to = mock.Mock(return_value=motion_result(False))
        picker._hold = mock.Mock()

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            success = picker.run("red")

        self.assertFalse(success)
        self.assertEqual(picker._move_to.call_count, 1)
        picker._hold.assert_called_once_with(
            30, gripper=scripted_pick.so101.GRIPPER_OPEN, recorder=None
        )
        self.assertNotIn(
            scripted_pick.so101.GRIPPER_CLOSE,
            [call.kwargs["gripper"] for call in picker._hold.call_args_list],
        )
        self.assertIn("[pick] abort reason=pregrasp_not_converged", output.getvalue())

    def test_run_aborts_before_close_and_lift_when_grasp_does_not_converge(self):
        picker = make_picker()
        picker._move_to = mock.Mock(side_effect=[motion_result(True), motion_result(False)])
        picker._hold = mock.Mock()

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            success = picker.run("red")

        self.assertFalse(success)
        self.assertEqual(picker._move_to.call_count, 2)
        self.assertEqual(
            [call.kwargs["phase"] for call in picker._move_to.call_args_list],
            ["pregrasp", "grasp"],
        )
        self.assertNotIn(
            scripted_pick.so101.GRIPPER_CLOSE,
            [call.kwargs["gripper"] for call in picker._hold.call_args_list],
        )
        self.assertIn("[pick] abort reason=grasp_not_converged", output.getvalue())

    def test_at_close_log_names_target_actual_and_cube_errors(self):
        picker = make_picker()
        picker._move_to = mock.Mock(return_value=motion_result(True))
        picker._close_until_contact = mock.Mock(return_value=True)
        picker._grasp_gripper_cmd = 0.1
        picker._hold = mock.Mock()
        picker._gripper_q = mock.Mock(return_value=0.1)
        picker._tip_pos = mock.Mock(return_value=np.array([0.202, -0.014, 0.776]))
        picker._success = mock.Mock(return_value=True)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            success = picker.run("red")

        self.assertTrue(success)
        at_close = next(
            line for line in output.getvalue().splitlines() if "[pick] at_close" in line
        )
        for field in (
            "cube=",
            "target_tip=",
            "actual_tip=",
            "target_xy_err=",
            "target_z_err=",
            "cube_xy_err=",
            "cube_z_err=",
        ):
            self.assertIn(field, at_close)


class ContactGatedCloseTests(unittest.TestCase):
    def test_contact_pad_geom_resolution_is_logged(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            make_picker()

        self.assertIn(
            "[pick] contact pads fixed_geom=26 moving_geom=27", output.getvalue()
        )

    def test_contact_links_resolve_unique_active_box_pad_geoms(self):
        picker = make_picker()

        self.assertTrue(hasattr(picker, "fixed_finger_geom_idx"))
        self.assertTrue(hasattr(picker, "moving_finger_geom_idx"))
        self.assertEqual(picker.fixed_finger_geom_idx, 26)
        self.assertEqual(picker.moving_finger_geom_idx, 27)

    def test_contact_link_without_unique_active_box_pad_is_rejected(self):
        bad_fixed = FakeLink(
            idx=10,
            geoms=[FakeGeom(24, n_verts=252), FakeGeom(25, n_verts=775)],
        )
        moving = FakeLink(idx=20, geoms=[FakeGeom(27)])

        with self.assertRaisesRegex(RuntimeError, "gripper.*pad geom"):
            make_picker(
                robot=FakeRobot(
                    links={"gripper": bad_fixed, "moving_jaw_so101_v1": moving}
                )
            )

    def test_close_succeeds_only_after_bilateral_contact_and_tightening(self):
        bilateral = pad_contact(26, 27, force=2.5)
        robot = FakeRobot(
            contacts=[{}] * 199
            + [bilateral] * (1 + scripted_pick.TIGHTEN_STEPS)
        )
        picker = make_picker(robot=robot)
        cube = picker.bundle.cubes["red"]
        arm_goal = np.array([0.1, 0.2, 0.3, math.pi / 2, math.pi / 2])
        measured_at_contact = 0.5
        picker._gripper_q = mock.Mock(
            side_effect=lambda: (
                scripted_pick.so101.GRIPPER_OPEN
                if not robot.commands
                else measured_at_contact
            )
        )

        with contextlib.redirect_stdout(io.StringIO()):
            success = picker._close_until_contact(
                cube, arm_goal, np.zeros(3), recorder=None
            )

        self.assertTrue(success)
        self.assertEqual(len(robot.commands), 200 + scripted_pick.TIGHTEN_STEPS)
        for command in robot.commands:
            np.testing.assert_allclose(command[:5], arm_goal)
        self.assertLess(robot.commands[0][-1], scripted_pick.so101.GRIPPER_OPEN)
        self.assertGreater(robot.commands[0][-1], scripted_pick.so101.GRIPPER_CLOSE)
        self.assertLess(robot.commands[1][-1], robot.commands[0][-1])
        expected_endpoint = max(
            scripted_pick.so101.GRIPPER_CLOSE,
            measured_at_contact - scripted_pick.CONTACT_TIGHTEN,
        )
        contact_command = robot.commands[199][-1]
        self.assertGreater(expected_endpoint, contact_command)
        self.assertLess(expected_endpoint, measured_at_contact)
        self.assertAlmostEqual(robot.commands[-1][-1], expected_endpoint)
        self.assertAlmostEqual(picker._grasp_gripper_cmd, expected_endpoint)

    def test_close_tightening_endpoint_is_clamped_at_gripper_close(self):
        fixed_only = pad_contact(26)
        bilateral = pad_contact(26, 27)
        robot = FakeRobot(
            contacts=[fixed_only] * (scripted_pick.CLOSE_RAMP_STEPS - 1)
            + [bilateral] * (1 + scripted_pick.TIGHTEN_STEPS)
        )
        picker = make_picker(robot=robot)
        picker._gripper_q = mock.Mock(return_value=0.01)

        with contextlib.redirect_stdout(io.StringIO()):
            success = picker._close_until_contact(
                picker.bundle.cubes["red"], np.zeros(5), np.zeros(3)
            )

        self.assertTrue(success)
        self.assertAlmostEqual(
            robot.commands[-1][-1], scripted_pick.so101.GRIPPER_CLOSE
        )
        self.assertAlmostEqual(
            picker._grasp_gripper_cmd, scripted_pick.so101.GRIPPER_CLOSE
        )

    def test_close_fails_when_ramp_ends_without_bilateral_contact(self):
        robot = FakeRobot(contacts=[pad_contact(26)] * scripted_pick.CLOSE_RAMP_STEPS)
        picker = make_picker(robot=robot)
        picker._grasp_gripper_cmd = 0.42

        with contextlib.redirect_stdout(io.StringIO()):
            success = picker._close_until_contact(
                picker.bundle.cubes["red"], np.zeros(5), np.zeros(3)
            )

        self.assertFalse(success)
        self.assertEqual(picker._close_failure_reason, "no_bilateral_contact")
        self.assertIsNone(picker._grasp_gripper_cmd)
        self.assertEqual(len(robot.commands), scripted_pick.CLOSE_RAMP_STEPS)

    def test_close_fails_after_more_than_five_consecutive_lost_contacts(self):
        bilateral = pad_contact(26, 27)
        robot = FakeRobot(contacts=[bilateral] + [pad_contact(26)] * 6)
        picker = make_picker(robot=robot)

        with contextlib.redirect_stdout(io.StringIO()):
            success = picker._close_until_contact(
                picker.bundle.cubes["red"], np.zeros(5), np.zeros(3)
            )

        self.assertFalse(success)
        self.assertEqual(picker._close_failure_reason, "contact_lost")
        self.assertEqual(len(robot.commands), 7)

    def test_five_consecutive_lost_contacts_are_tolerated_if_contact_resumes(self):
        fixed_only = pad_contact(26)
        bilateral = pad_contact(26, 27)
        robot = FakeRobot(
            contacts=[bilateral]
            + [fixed_only] * scripted_pick.CONTACT_LOST_MAX_STEPS
            + [bilateral]
            * (scripted_pick.TIGHTEN_STEPS - scripted_pick.CONTACT_LOST_MAX_STEPS)
        )
        picker = make_picker(robot=robot)

        with contextlib.redirect_stdout(io.StringIO()):
            success = picker._close_until_contact(
                picker.bundle.cubes["red"], np.zeros(5), np.zeros(3)
            )

        self.assertTrue(success)
        self.assertIsNone(picker._close_failure_reason)
        self.assertEqual(len(robot.commands), 1 + scripted_pick.TIGHTEN_STEPS)

    def test_close_fails_when_final_tighten_sample_is_not_bilateral(self):
        fixed_only = pad_contact(26)
        bilateral = pad_contact(26, 27)
        robot = FakeRobot(
            contacts=[bilateral] * scripted_pick.TIGHTEN_STEPS + [fixed_only]
        )
        picker = make_picker(robot=robot)

        with contextlib.redirect_stdout(io.StringIO()):
            success = picker._close_until_contact(
                picker.bundle.cubes["red"], np.zeros(5), np.zeros(3)
            )

        self.assertFalse(success)
        self.assertEqual(picker._close_failure_reason, "contact_lost")
        self.assertIsNone(picker._grasp_gripper_cmd)
        self.assertEqual(len(robot.commands), 1 + scripted_pick.TIGHTEN_STEPS)

    def test_close_logs_contact_force_command_state_and_tcp_error(self):
        bilateral = pad_contact(26, 27, force=3.0)
        robot = FakeRobot(
            contacts=[bilateral] * (1 + scripted_pick.TIGHTEN_STEPS)
        )
        picker = make_picker(robot=robot)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            picker._close_until_contact(
                picker.bundle.cubes["red"], np.zeros(5), np.zeros(3)
            )

        log = output.getvalue()
        for field in (
            "step=",
            "fixed_contact=",
            "moving_contact=",
            "contacts=",
            "max_force=",
            "gripper_cmd=",
            "gripper_q=",
            "tcp_err=",
        ):
            self.assertIn(field, log)
        for field in ("contact_cmd=", "contact_q=", "tighten_target="):
            self.assertIn(field, log)

    def test_required_contact_links_are_resolved_by_exact_name(self):
        for missing_name, links in (
            (
                "gripper",
                {"moving_jaw_so101_v1": FakeLink(idx=20, geoms=[FakeGeom(27)])},
            ),
            (
                "moving_jaw_so101_v1",
                {"gripper": FakeLink(idx=10, geoms=[FakeGeom(26)])},
            ),
        ):
            with self.subTest(missing_name=missing_name):
                with self.assertRaisesRegex(
                    RuntimeError, rf"{missing_name}.*bilateral contact"
                ):
                    make_picker(robot=FakeRobot(links=links))

    def test_finger_contacts_queries_cube_and_classifies_torch_like_arrays(self):
        cube = object()
        contacts = {
            "geom_a": TorchLikeTensor([26, 27]),
            "geom_b": TorchLikeTensor([99, 99]),
            "link_a": TorchLikeTensor([19, 20]),
            "link_b": TorchLikeTensor([99, 99]),
            "force_a": TorchLikeTensor([[0.0, 0.0, 2.0], [0.0, 3.0, 4.0]]),
        }
        robot = FakeRobot(contacts=[contacts])
        picker = make_picker(robot=robot)

        summary = picker._finger_contacts(cube)

        self.assertEqual(robot.contact_queries, [cube])
        self.assertTrue(summary.bilateral)
        self.assertEqual(summary.count, 2)
        self.assertEqual(summary.max_force, 5.0)


class RunContactGateTests(unittest.TestCase):
    def test_run_does_not_lift_after_close_failure(self):
        picker = make_picker()
        picker._move_to = mock.Mock(return_value=motion_result(True))
        picker._close_until_contact = mock.Mock(return_value=False)
        picker._close_failure_reason = "no_bilateral_contact"
        picker._hold = mock.Mock()

        with contextlib.redirect_stdout(io.StringIO()):
            success = picker.run("red")

        self.assertFalse(success)
        self.assertEqual(picker._move_to.call_count, 2)
        picker._hold.assert_called_once_with(
            30, gripper=scripted_pick.so101.GRIPPER_OPEN, recorder=None
        )

    def test_run_passes_converged_grasp_goal_and_target_to_close(self):
        picker = make_picker()
        arm_goal = np.array([0.1, 0.2, 0.3, math.pi / 2, math.pi / 2])
        target_tip = np.array([0.2, -0.015, 0.775])
        picker._move_to = mock.Mock(
            side_effect=[
                motion_result(True),
                motion_result(True, arm_goal=arm_goal, target_tip=target_tip),
                motion_result(True),
                motion_result(True),
                motion_result(True),
            ]
        )
        picker._close_until_contact = mock.Mock(return_value=True)
        picker._grasp_gripper_cmd = 0.2
        picker._hold = mock.Mock()
        picker._gripper_q = mock.Mock(return_value=0.1)
        picker._tip_pos = mock.Mock(return_value=target_tip)
        picker._success = mock.Mock(return_value=True)
        recorder = object()

        with contextlib.redirect_stdout(io.StringIO()):
            success = picker.run("red", recorder=recorder)

        self.assertTrue(success)
        picker._close_until_contact.assert_called_once_with(
            picker.bundle.cubes["red"], arm_goal, target_tip, recorder
        )

    def test_run_holds_successful_tighten_command_through_lift_and_place(self):
        picker = make_picker()
        grasp_command = 0.83
        picker._move_to = mock.Mock(return_value=motion_result(True))

        def close_success(*args):
            picker._grasp_gripper_cmd = grasp_command
            return True

        picker._close_until_contact = mock.Mock(side_effect=close_success)
        picker._hold = mock.Mock()
        picker._gripper_q = mock.Mock(return_value=grasp_command)
        picker._tip_pos = mock.Mock(return_value=np.zeros(3))
        picker._success = mock.Mock(return_value=True)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            success = picker.run("red")

        self.assertTrue(success)
        phase_calls = {
            call.kwargs["phase"]: call for call in picker._move_to.call_args_list
        }
        self.assertEqual(phase_calls["lift"].kwargs["gripper"], grasp_command)
        self.assertEqual(phase_calls["place"].kwargs["gripper"], grasp_command)
        self.assertNotEqual(grasp_command, scripted_pick.so101.GRIPPER_CLOSE)
        self.assertIn("gripper_cmd=0.830", output.getvalue())
        self.assertNotIn("target_close=", output.getvalue())


class MotionConvergenceTests(unittest.TestCase):
    def test_move_requires_five_consecutive_tcp_samples_and_logs_result(self):
        picker = make_picker()
        requested_tip = np.array([0.2, 0.1, 0.8])
        target_tip = scripted_pick._with_finger_offset(requested_tip)
        arm_goal = np.array([0.1, -0.2, 0.3, math.pi / 2, math.pi / 2])
        picker.robot.qpos[:5] = arm_goal
        picker._ik = mock.Mock(return_value=(arm_goal.copy(), 0.0123))
        picker._cmd = mock.Mock()
        errors = [
            0.005,
            0.004,
            0.003,
            0.002,
            0.02,
            0.0059,
            0.005,
            0.004,
            0.003,
            0.002,
        ]
        picker._tip_pos = mock.Mock(
            side_effect=[target_tip + np.array([error, 0.0, 0.0]) for error in errors]
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = picker._move_to(
                requested_tip,
                phase="grasp",
                gripper=scripted_pick.so101.GRIPPER_OPEN,
            )

        self.assertTrue(result.converged)
        self.assertEqual(result.interp_steps, scripted_pick.MOVE_MIN_STEPS)
        self.assertEqual(result.settle_steps, 10)
        self.assertEqual(picker._tip_pos.call_count, 10)
        self.assertEqual(picker._cmd.call_count, scripted_pick.MOVE_MIN_STEPS + 10)
        np.testing.assert_allclose(result.arm_goal, arm_goal)
        np.testing.assert_allclose(result.target_tip, target_tip)
        np.testing.assert_allclose(result.actual_tip, target_tip + [0.002, 0.0, 0.0])
        np.testing.assert_allclose(result.error_vector, [0.002, 0.0, 0.0])
        self.assertAlmostEqual(result.tcp_error, 0.002)
        self.assertAlmostEqual(result.ik_error, 0.0123)
        self.assertAlmostEqual(result.joint_error, 0.0)
        line = output.getvalue()
        for field in (
            "phase=grasp",
            "target_tip=",
            "actual_tip=",
            "error_vec=",
            "tcp_err=",
            "ik_err=",
            "joint_err=",
            "interp_steps=",
            "settle_steps=",
            "converged=",
        ):
            self.assertIn(field, line)

    def test_move_terminates_non_converged_after_max_settle_steps(self):
        picker = make_picker()
        requested_tip = np.array([0.2, 0.1, 0.8])
        target_tip = scripted_pick._with_finger_offset(requested_tip)
        arm_goal = picker.robot.qpos[:5].copy()
        picker._ik = mock.Mock(return_value=(arm_goal, float("nan")))
        picker._cmd = mock.Mock()
        picker._tip_pos = mock.Mock(return_value=target_tip + [0.007, 0.0, 0.0])

        with contextlib.redirect_stdout(io.StringIO()):
            result = picker._move_to(
                requested_tip,
                phase="grasp",
                gripper=scripted_pick.so101.GRIPPER_OPEN,
            )

        self.assertFalse(result.converged)
        self.assertEqual(result.settle_steps, scripted_pick.MOVE_SETTLE_MAX_STEPS)
        self.assertEqual(
            picker._cmd.call_count,
            scripted_pick.MOVE_MIN_STEPS + scripted_pick.MOVE_SETTLE_MAX_STEPS,
        )


class InverseKinematicsTests(unittest.TestCase):
    def test_ik_returns_position_residual_from_error_pose(self):
        class ResidualRobot(FakeRobot):
            def __init__(self):
                super().__init__()
                self.calls = []

            def inverse_kinematics(self, **kwargs):
                self.calls.append(kwargs)
                return TorchLikeTensor(
                    [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
                ), TorchLikeTensor([3.0, 4.0, 0.0, 99.0, 98.0, 97.0])

        robot = ResidualRobot()
        picker = make_picker(robot=robot)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            q, ik_error = picker._ik(np.array([0.2, 0.1, 0.8]))

        np.testing.assert_allclose(q, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        self.assertEqual(ik_error, 5.0)
        call = robot.calls[0]
        self.assertTrue(call["return_error"])
        self.assertEqual(call["local_point"], [0.0, 0.0, -scripted_pick.so101.EE_TIP_OFFSET])
        self.assertIn("init_qpos", call)
        self.assertEqual(call["max_samples"], 80)
        self.assertEqual(call["max_solver_iters"], 40)
        self.assertEqual(call["dofs_idx_local"], scripted_pick.IK_DOFS)
        self.assertIn("[pick] IK api path=local_point_init residual=True", output.getvalue())

    def test_ik_falls_back_without_residual_and_logs_api_path_once(self):
        class NoResidualRobot(FakeRobot):
            def __init__(self):
                super().__init__()
                self.calls = []

            def inverse_kinematics(self, **kwargs):
                self.calls.append(kwargs)
                if "return_error" in kwargs:
                    raise TypeError(
                        "inverse_kinematics() got an unexpected keyword argument "
                        "'return_error'"
                    )
                return TorchLikeTensor([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])

        robot = NoResidualRobot()
        picker = make_picker(robot=robot)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            first_q, first_error = picker._ik(np.array([0.2, 0.1, 0.8]))
            second_q, second_error = picker._ik(np.array([0.2, 0.1, 0.8]))

        np.testing.assert_allclose(first_q, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        np.testing.assert_allclose(second_q, first_q)
        self.assertTrue(math.isnan(first_error))
        self.assertTrue(math.isnan(second_error))
        selected_calls = [call for call in robot.calls if "return_error" not in call]
        self.assertEqual(len(selected_calls), 2)
        self.assertIn("local_point", selected_calls[0])
        self.assertIn("init_qpos", selected_calls[0])
        self.assertEqual(output.getvalue().count("[pick] IK api path="), 1)
        self.assertIn(
            "[pick] IK api path=local_point_init residual=False", output.getvalue()
        )

    def test_ik_removes_only_unsupported_init_qpos(self):
        class NoInitRobot(FakeRobot):
            def __init__(self):
                super().__init__()
                self.calls = []

            def inverse_kinematics(self, **kwargs):
                self.calls.append(kwargs)
                if "init_qpos" in kwargs:
                    raise TypeError(
                        "inverse_kinematics() got an unexpected keyword argument "
                        "'init_qpos'"
                    )
                return TorchLikeTensor(
                    [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
                ), TorchLikeTensor([0.0, 0.003, 0.004, 1.0, 2.0, 3.0])

        robot = NoInitRobot()
        picker = make_picker(robot=robot)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            q, ik_error = picker._ik(np.array([0.2, 0.1, 0.8]))

        np.testing.assert_allclose(q, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        self.assertAlmostEqual(ik_error, 0.005)
        self.assertEqual(len(robot.calls), 2)
        self.assertNotIn("init_qpos", robot.calls[1])
        self.assertIn("local_point", robot.calls[1])
        self.assertTrue(robot.calls[1]["return_error"])
        self.assertIn("[pick] IK api path=local_point residual=True", output.getvalue())

    def test_ik_switches_to_link_origin_only_for_unsupported_local_point(self):
        class NoLocalPointRobot(FakeRobot):
            def __init__(self):
                super().__init__()
                self.calls = []

            def inverse_kinematics(self, **kwargs):
                self.calls.append(kwargs)
                if "local_point" in kwargs:
                    raise TypeError(
                        "inverse_kinematics() got an unexpected keyword argument "
                        "'local_point'"
                    )
                return TorchLikeTensor(
                    [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
                ), TorchLikeTensor([0.001, 0.002, 0.002, 1.0, 2.0, 3.0])

        robot = NoLocalPointRobot()
        picker = make_picker(robot=robot)
        requested_tip = np.array([0.2, 0.1, 0.8])

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            q, ik_error = picker._ik(requested_tip)

        np.testing.assert_allclose(q, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        self.assertAlmostEqual(ik_error, 0.003)
        self.assertEqual(len(robot.calls), 2)
        selected = robot.calls[1]
        self.assertNotIn("local_point", selected)
        self.assertIn("init_qpos", selected)
        self.assertTrue(selected["return_error"])
        expected_tip = scripted_pick._with_finger_offset(requested_tip)
        np.testing.assert_allclose(
            selected["pos"], scripted_pick._tip_to_link_pos(expected_tip)
        )
        self.assertIn(
            "[pick] IK api path=link_origin_init residual=True", output.getvalue()
        )

    def test_ik_propagates_unrelated_type_error_without_retrying(self):
        class BrokenRobot(FakeRobot):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def inverse_kinematics(self, **kwargs):
                self.calls += 1
                raise TypeError("solver exploded internally")

        robot = BrokenRobot()
        picker = make_picker(robot=robot)

        with self.assertRaisesRegex(TypeError, "solver exploded internally"):
            picker._ik(np.array([0.2, 0.1, 0.8]))

        self.assertEqual(robot.calls, 1)


class CommandTests(unittest.TestCase):
    def test_cmd_does_not_mutate_caller_arm_array(self):
        robot = FakeRobot()
        robot.control_dofs_position = mock.Mock()
        picker = make_picker(robot=robot)
        arm = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        original = arm.copy()

        picker._cmd(arm, scripted_pick.so101.GRIPPER_OPEN, recorder=None)

        np.testing.assert_array_equal(arm, original)


if __name__ == "__main__":
    unittest.main()
