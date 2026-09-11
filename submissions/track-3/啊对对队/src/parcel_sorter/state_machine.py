from __future__ import annotations

from enum import Enum

from .contracts import ControlDecision, Observation


class Stage(str, Enum):
    DETECT = "detect"
    APPROACH = "approach"
    GRASP = "grasp"
    VERIFY = "verify"
    LIFT = "lift"
    PLACE = "place"
    RECOVER_SETDOWN = "recover_setdown"
    RECOVER_RELEASE = "recover_release"
    RELEASE = "release"
    COMPLETE = "complete"
    ABORT = "abort"


class Command(str, Enum):
    SEARCH = "search"
    MOVE_PREGRASP = "move_pregrasp"
    CLOSE_GRIPPER = "close_gripper"
    HOLD = "hold"
    MOVE_LIFT = "move_lift"
    MOVE_DROP = "move_drop"
    MOVE_RECOVERY_SETDOWN = "move_recovery_setdown"
    OPEN_GRIPPER = "open_gripper"
    STOP = "stop"


class ClosedLoopSupervisor:
    """Deterministic safety and retry layer around a learned manipulation policy."""

    def __init__(
        self,
        max_grasp_retries: int = 2,
        grasp_settle_steps: int = 0,
        release_settle_steps: int = 0,
        grasp_stability_steps: int = 1,
        transport_slip_setdown_regrasp_enabled: bool = False,
        recovery_setdown_max_steps: int = 20,
    ) -> None:
        if min(max_grasp_retries, grasp_settle_steps, release_settle_steps) < 0:
            raise ValueError("retry and settle counts cannot be negative")
        if grasp_stability_steps < 1:
            raise ValueError("grasp_stability_steps must be positive")
        if recovery_setdown_max_steps < 1:
            raise ValueError("recovery_setdown_max_steps must be positive")
        self.max_grasp_retries = max_grasp_retries
        self.grasp_settle_steps = grasp_settle_steps
        self.release_settle_steps = release_settle_steps
        self.grasp_stability_steps = grasp_stability_steps
        self.transport_slip_setdown_regrasp_enabled = (
            transport_slip_setdown_regrasp_enabled
        )
        self.recovery_setdown_max_steps = recovery_setdown_max_steps
        self.retry_count = 0
        self._verify_wait_steps = 0
        self._grasp_contact_steps = 0
        self._lift_contact_loss_steps = 0
        self._release_wait_steps = 0
        self._recovery_setdown_steps = 0
        self._recovery_release_steps = 0
        self.stage = Stage.DETECT

    def reset(self) -> None:
        self.retry_count = 0
        self._verify_wait_steps = 0
        self._grasp_contact_steps = 0
        self._lift_contact_loss_steps = 0
        self._release_wait_steps = 0
        self._recovery_setdown_steps = 0
        self._recovery_release_steps = 0
        self.stage = Stage.DETECT

    def step(self, observation: Observation) -> ControlDecision:
        if self.stage in {Stage.COMPLETE, Stage.ABORT}:
            return self._decision(Command.STOP, "episode already terminal")

        if observation.fault or observation.excessive_contact_force:
            self.stage = Stage.ABORT
            return self._decision(Command.STOP, "safety fault")

        if (
            self.transport_slip_setdown_regrasp_enabled
            and observation.transport_slip
            and self.stage in {Stage.LIFT, Stage.PLACE}
        ):
            self._recovery_setdown_steps = 1
            self._recovery_release_steps = 0
            self.stage = Stage.RECOVER_SETDOWN
            return self._decision(
                Command.MOVE_RECOVERY_SETDOWN,
                "transport slip detected; setting parcel down",
            )

        if self.stage == Stage.RECOVER_SETDOWN:
            if (
                observation.at_recovery_setdown
                or self._recovery_setdown_steps >= self.recovery_setdown_max_steps
            ):
                self._recovery_release_steps = 0
                self.stage = Stage.RECOVER_RELEASE
                return self._decision(
                    Command.OPEN_GRIPPER,
                    "recovery setdown reached; releasing parcel",
                )
            self._recovery_setdown_steps += 1
            return self._decision(
                Command.MOVE_RECOVERY_SETDOWN,
                "lowering slipped parcel",
            )

        if self.stage == Stage.RECOVER_RELEASE:
            if observation.grasp_contact:
                self._recovery_release_steps = 0
                return self._decision(
                    Command.OPEN_GRIPPER,
                    "waiting for recovery release",
                )
            self._recovery_release_steps += 1
            if self._recovery_release_steps < 2:
                return self._decision(
                    Command.OPEN_GRIPPER,
                    "confirming recovery release",
                )
            if self.retry_count >= self.max_grasp_retries:
                self.stage = Stage.ABORT
                return self._decision(
                    Command.STOP,
                    "transport slip recovery exhausted retry budget",
                )
            self.retry_count += 1
            self._recovery_setdown_steps = 0
            self._recovery_release_steps = 0
            self.stage = Stage.DETECT
            return self._decision(
                Command.SEARCH,
                "transport slip set down; retrying",
            )

        if self.stage == Stage.DETECT:
            if observation.parcel_visible:
                self.stage = Stage.APPROACH
                return self._decision(Command.MOVE_PREGRASP, "parcel acquired")
            return self._decision(Command.SEARCH, "waiting for parcel")

        if self.stage == Stage.APPROACH:
            if observation.at_pregrasp:
                self.stage = Stage.GRASP
                return self._decision(Command.CLOSE_GRIPPER, "pregrasp reached")
            return self._decision(Command.MOVE_PREGRASP, "approaching parcel")

        if self.stage == Stage.GRASP:
            self._grasp_contact_steps = 0
            self.stage = Stage.VERIFY
            return self._decision(Command.HOLD, "checking contact")

        if self.stage == Stage.VERIFY:
            if observation.grasp_contact:
                self._grasp_contact_steps += 1
                if self._grasp_contact_steps >= self.grasp_stability_steps:
                    self._verify_wait_steps = 0
                    self._grasp_contact_steps = 0
                    self.stage = Stage.LIFT
                    return self._decision(Command.MOVE_LIFT, "stable grasp verified")
                return self._decision(Command.HOLD, "stabilizing gripper contact")
            self._grasp_contact_steps = 0
            if self._verify_wait_steps < self.grasp_settle_steps:
                self._verify_wait_steps += 1
                return self._decision(Command.HOLD, "waiting for gripper contact")
            return self._retry_or_abort("grasp verification failed")

        if self.stage == Stage.LIFT:
            if observation.parcel_lifted:
                self._lift_contact_loss_steps = 0
                self.stage = Stage.PLACE
                return self._decision(Command.MOVE_DROP, "parcel lifted")
            if observation.grasp_contact:
                self._lift_contact_loss_steps = 0
            else:
                self._lift_contact_loss_steps += 1
                if self._lift_contact_loss_steps > max(2, self.grasp_settle_steps):
                    return self._retry_or_abort("grasp lost during lift")
            return self._decision(Command.MOVE_LIFT, "lifting parcel")

        if self.stage == Stage.PLACE:
            if observation.at_drop_pose:
                self._release_wait_steps = 0
                self.stage = Stage.RELEASE
                return self._decision(Command.OPEN_GRIPPER, "drop pose reached")
            return self._decision(Command.MOVE_DROP, "moving to destination")

        if self.stage == Stage.RELEASE:
            if observation.parcel_released:
                self._release_wait_steps = 0
                self.stage = Stage.COMPLETE
                return self._decision(Command.STOP, "parcel sorted")
            self._release_wait_steps += 1
            if (
                self._release_wait_steps > max(2, self.release_settle_steps * 2)
                and not observation.parcel_in_bin
            ):
                return self._retry_or_abort("parcel missed destination")
            return self._decision(Command.OPEN_GRIPPER, "releasing parcel")

        raise RuntimeError(f"unhandled stage: {self.stage}")

    def _retry_or_abort(self, reason: str) -> ControlDecision:
        self._verify_wait_steps = 0
        self._grasp_contact_steps = 0
        self._lift_contact_loss_steps = 0
        self._release_wait_steps = 0
        self._recovery_setdown_steps = 0
        self._recovery_release_steps = 0
        if self.retry_count >= self.max_grasp_retries:
            self.stage = Stage.ABORT
            return self._decision(Command.STOP, reason)
        self.retry_count += 1
        self.stage = Stage.DETECT
        return self._decision(Command.SEARCH, reason)

    def _decision(self, command: Command, reason: str) -> ControlDecision:
        return ControlDecision(
            stage=self.stage.value,
            command=command.value,
            reason=reason,
            retry_count=self.retry_count,
        )
