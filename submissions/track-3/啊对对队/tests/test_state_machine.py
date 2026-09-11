import unittest

from parcel_sorter.contracts import Observation
from parcel_sorter.state_machine import ClosedLoopSupervisor, Command, Stage


class ClosedLoopSupervisorTests(unittest.TestCase):
    def test_requires_consecutive_stable_grasp_contact(self) -> None:
        supervisor = ClosedLoopSupervisor(grasp_settle_steps=5, grasp_stability_steps=3)
        supervisor.step(Observation(parcel_visible=True))
        supervisor.step(Observation(at_pregrasp=True))
        supervisor.step(Observation())

        first = supervisor.step(Observation(grasp_contact=True))
        interrupted = supervisor.step(Observation(grasp_contact=False))
        second_first = supervisor.step(Observation(grasp_contact=True))
        second = supervisor.step(Observation(grasp_contact=True))
        third = supervisor.step(Observation(grasp_contact=True))

        self.assertEqual(first.command, Command.HOLD.value)
        self.assertEqual(interrupted.command, Command.HOLD.value)
        self.assertEqual(second_first.command, Command.HOLD.value)
        self.assertEqual(second.command, Command.HOLD.value)
        self.assertEqual(third.command, Command.MOVE_LIFT.value)

    def test_success_after_one_failed_grasp(self) -> None:
        supervisor = ClosedLoopSupervisor(max_grasp_retries=2)
        observations = [
            Observation(parcel_visible=True),
            Observation(at_pregrasp=True),
            Observation(),
            Observation(),
            Observation(parcel_visible=True),
            Observation(at_pregrasp=True),
            Observation(),
            Observation(grasp_contact=True),
            Observation(parcel_lifted=True),
            Observation(at_drop_pose=True, parcel_lifted=True),
            Observation(at_drop_pose=True, parcel_released=True),
        ]

        decisions = [supervisor.step(observation) for observation in observations]

        self.assertEqual(supervisor.stage, Stage.COMPLETE)
        self.assertEqual(supervisor.retry_count, 1)
        self.assertEqual(decisions[-1].command, Command.STOP.value)
        self.assertIn(Command.MOVE_LIFT.value, [decision.command for decision in decisions])

    def test_abort_after_retry_budget_is_exhausted(self) -> None:
        supervisor = ClosedLoopSupervisor(max_grasp_retries=0)
        supervisor.step(Observation(parcel_visible=True))
        supervisor.step(Observation(at_pregrasp=True))
        supervisor.step(Observation())

        decision = supervisor.step(Observation())

        self.assertEqual(supervisor.stage, Stage.ABORT)
        self.assertEqual(decision.command, Command.STOP.value)

    def test_excessive_force_aborts_immediately(self) -> None:
        supervisor = ClosedLoopSupervisor(max_grasp_retries=2)

        decision = supervisor.step(Observation(excessive_contact_force=True))

        self.assertEqual(supervisor.stage, Stage.ABORT)
        self.assertEqual(decision.reason, "safety fault")

    def test_release_keeps_gripper_open_if_arm_drifts_from_drop_pose(self) -> None:
        supervisor = ClosedLoopSupervisor(max_grasp_retries=2)
        supervisor.stage = Stage.PLACE

        at_drop = supervisor.step(Observation(at_drop_pose=True, parcel_lifted=True))
        after_drift = supervisor.step(Observation())

        self.assertEqual(supervisor.stage, Stage.RELEASE)
        self.assertEqual(at_drop.command, Command.OPEN_GRIPPER.value)
        self.assertEqual(after_drift.command, Command.OPEN_GRIPPER.value)

    def test_missed_destination_starts_recovery_after_release_grace(self) -> None:
        supervisor = ClosedLoopSupervisor(max_grasp_retries=2, release_settle_steps=2)
        supervisor.stage = Stage.RELEASE

        decisions = [supervisor.step(Observation(parcel_in_bin=False)) for _ in range(5)]

        self.assertEqual(supervisor.stage, Stage.DETECT)
        self.assertEqual(supervisor.retry_count, 1)
        self.assertEqual(decisions[-1].command, Command.SEARCH.value)
        self.assertEqual(decisions[-1].reason, "parcel missed destination")

    def test_lost_grasp_during_lift_starts_recovery(self) -> None:
        supervisor = ClosedLoopSupervisor(max_grasp_retries=2, grasp_settle_steps=2)
        supervisor.stage = Stage.LIFT

        decisions = [supervisor.step(Observation(grasp_contact=False)) for _ in range(3)]

        self.assertEqual(supervisor.stage, Stage.DETECT)
        self.assertEqual(decisions[-1].reason, "grasp lost during lift")

    def test_transport_slip_runs_bounded_setdown_release_and_retry(self) -> None:
        supervisor = ClosedLoopSupervisor(
            max_grasp_retries=2,
            transport_slip_setdown_regrasp_enabled=True,
            recovery_setdown_max_steps=3,
        )
        supervisor.stage = Stage.PLACE

        detected = supervisor.step(Observation(transport_slip=True))
        lowering = supervisor.step(Observation())
        release = supervisor.step(Observation(at_recovery_setdown=True))
        confirm = supervisor.step(Observation(grasp_contact=False))
        retry = supervisor.step(Observation(grasp_contact=False))

        self.assertEqual(detected.command, Command.MOVE_RECOVERY_SETDOWN.value)
        self.assertEqual(lowering.command, Command.MOVE_RECOVERY_SETDOWN.value)
        self.assertEqual(release.command, Command.OPEN_GRIPPER.value)
        self.assertEqual(confirm.command, Command.OPEN_GRIPPER.value)
        self.assertEqual(retry.command, Command.SEARCH.value)
        self.assertEqual(supervisor.stage, Stage.DETECT)
        self.assertEqual(supervisor.retry_count, 1)

    def test_transport_slip_setdown_is_disabled_by_default(self) -> None:
        supervisor = ClosedLoopSupervisor()
        supervisor.stage = Stage.PLACE

        decision = supervisor.step(Observation(transport_slip=True))

        self.assertEqual(decision.command, Command.MOVE_DROP.value)
        self.assertEqual(supervisor.stage, Stage.PLACE)

    def test_transport_slip_releases_before_aborting_exhausted_retry(self) -> None:
        supervisor = ClosedLoopSupervisor(
            max_grasp_retries=0,
            transport_slip_setdown_regrasp_enabled=True,
            recovery_setdown_max_steps=1,
        )
        supervisor.stage = Stage.LIFT

        detected = supervisor.step(Observation(transport_slip=True))
        release = supervisor.step(Observation())
        supervisor.step(Observation(grasp_contact=False))
        terminal = supervisor.step(Observation(grasp_contact=False))

        self.assertEqual(detected.command, Command.MOVE_RECOVERY_SETDOWN.value)
        self.assertEqual(release.command, Command.OPEN_GRIPPER.value)
        self.assertEqual(terminal.command, Command.STOP.value)
        self.assertEqual(supervisor.stage, Stage.ABORT)


if __name__ == "__main__":
    unittest.main()
