"""Contact-quality state machine for contact-aware visual manipulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ContactVerifierConfig:
    min_consecutive_dual_finger_steps: int = 3
    min_contact_force: float = 0.0
    unverified_lift_grace_steps: int = 4


class ContactAwareGraspVerifier:
    """Verify that an assisted latch is supported by real dual-finger contact."""

    def __init__(self, config: ContactVerifierConfig = ContactVerifierConfig()) -> None:
        self.config = config
        self.reset()

    def reset(self) -> None:
        self.grasp_verified = False
        self.unverified_lift_steps = 0
        self.max_contact_force = 0.0
        self.max_consecutive_dual_finger_contact_steps = 0
        self.verification_events = 0

    def update(self, info: Mapping[str, object]) -> None:
        consecutive = int(info.get("consecutive_dual_finger_contact_steps", 0))
        force = float(info.get("robot_object_contact_force", 0.0))
        self.max_contact_force = max(self.max_contact_force, force)
        self.max_consecutive_dual_finger_contact_steps = max(
            self.max_consecutive_dual_finger_contact_steps, consecutive,
        )
        confirmed = (
            bool(info.get("is_grasped", False))
            and consecutive >= self.config.min_consecutive_dual_finger_steps
            and force >= self.config.min_contact_force
        )
        if confirmed and not self.grasp_verified:
            self.verification_events += 1
        self.grasp_verified |= confirmed
        if not bool(info.get("is_grasped", False)):
            self.grasp_verified = False

    def requires_recovery_before_transport(self) -> bool:
        """Return true only after a short grace period for latch establishment."""
        if self.grasp_verified:
            self.unverified_lift_steps = 0
            return False
        self.unverified_lift_steps += 1
        return self.unverified_lift_steps >= self.config.unverified_lift_grace_steps
