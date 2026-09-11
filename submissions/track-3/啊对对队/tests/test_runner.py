from dataclasses import replace
from pathlib import Path
import unittest

from parcel_sorter.config import load_config
from parcel_sorter.contracts import Observation, RobotState
from parcel_sorter.randomization import DomainRandomizer
from parcel_sorter.runner import resolve_grasp_stability_steps, run_expert_episode
from parcel_sorter.state_machine import Command


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeEnvironment:
    def __init__(self) -> None:
        self.control_step = 0
        self.prepared_decisions = []
        self.observations = (
            Observation(parcel_visible=True),
            Observation(at_pregrasp=True),
            Observation(),
            Observation(grasp_contact=True),
            Observation(parcel_lifted=True),
            Observation(at_drop_pose=True, parcel_lifted=True),
            Observation(at_drop_pose=True, parcel_released=True),
        )

    def state(self) -> RobotState:
        return RobotState(
            joint_positions=(0.0,) * 9,
            end_effector_pose=(0.5, 0.0, 0.2, 1.0, 0.0, 0.0, 0.0),
            parcel_pose=(0.6, 0.0, 0.02, 1.0, 0.0, 0.0, 0.0),
            target_position=(0.48, -0.34, 0.025),
            gripper_contact_force_n=1.0,
        )

    def observation(self, state=None):
        return self.observations[self.control_step]

    def step(self, action):
        self.control_step += 1

    def prepare_action(self, decision, state):
        self.prepared_decisions.append((decision.command, state.parcel_pose))

    def sensor_frame(self):
        return None, None

    def parcel_dropped(self):
        return False


class ExpertRunnerTests(unittest.TestCase):
    def test_planned_grasp_requires_configured_stable_contact_dwell(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        config = replace(
            config,
            task=replace(
                config.task,
                geometry_aware_grasp_planning_enabled=True,
                grasp_planning_stability_steps=10,
            ),
        )
        sample = replace(
            DomainRandomizer(config.randomization, config.seed).sample(0),
            shape="box",
            dimensions_m=(0.30, 0.07, 0.16),
        )

        self.assertEqual(resolve_grasp_stability_steps(config, sample), 10)

    def test_reset_gate_uses_planned_dwell_only_when_environment_activates_planner(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        config = replace(
            config,
            task=replace(
                config.task,
                geometry_aware_grasp_planning_enabled=True,
                grasp_planning_reset_fallback_gate_enabled=True,
                grasp_planning_stability_steps=10,
            ),
            control=replace(config.control, collision_checked_reset_enabled=True),
        )
        sample = replace(
            DomainRandomizer(config.randomization, config.seed).sample(0),
            shape="box",
            dimensions_m=(0.30, 0.07, 0.16),
        )

        self.assertEqual(
            resolve_grasp_stability_steps(
                config, sample, geometry_grasp_planning_active=False
            ),
            config.task.grasp_stability_steps,
        )
        self.assertEqual(
            resolve_grasp_stability_steps(
                config, sample, geometry_grasp_planning_active=True
            ),
            10,
        )

    def test_runs_complete_closed_loop(self) -> None:
        config = load_config(PROJECT_ROOT / "configs" / "baseline.toml")
        sample = DomainRandomizer(config.randomization, config.seed).sample(0)
        environment = FakeEnvironment()
        report = run_expert_episode(environment, config, sample, 0)

        self.assertTrue(report.result.success)
        self.assertEqual(report.terminal_stage, "complete")
        self.assertIn(Command.MOVE_LIFT.value, [item["command"] for item in report.trace])
        self.assertEqual(len(report.trace), len(environment.prepared_decisions))
        self.assertEqual(report.trace[0]["ee_quaternion_wxyz"], [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(report.trace[0]["parcel_quaternion_wxyz"], [1.0, 0.0, 0.0, 0.0])
        for actual, expected in zip(
            report.trace[0]["ee_parcel_relative_position_m"],
            (-0.1, 0.0, 0.18),
            strict=True,
        ):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(len(report.trace[0]["action_target_position_m"]), 3)


if __name__ == "__main__":
    unittest.main()
