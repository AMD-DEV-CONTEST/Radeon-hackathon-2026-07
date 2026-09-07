"""Session 7: MuJoCo-side port of controller_adapt.adapt_grasp_profile.

Re-exports the SAME co-adaptation rule Genesis uses (compliance -> close_force,
geometry -> hand_to_fingertip, object-shape -> yaw_offset/center_align) rather than a
fixed close_force for every design/object -- using a single hardcoded force for both
the baseline and the 3-finger winner would silently bias one design or the other, the
exact "fixed reward across changing bodies" trap controller_adapt.py's own docstring
warns about (project brief S5). Constants (BASE_CLOSE_FORCE, COMPLIANCE_FORCE_GAIN,
per-object yaw_offset/center_align) are copied verbatim from
franka_fruit_pick/codesign/controller_adapt.py, not re-derived or re-tuned.
"""
from __future__ import annotations

from dataclasses import dataclass

from gripper_gen import GripperParams, hand_to_fingertip_z

BASE_CLOSE_FORCE = -10.0  # N, at compliance = 0 (rigid) -- controller_adapt.BASE_CLOSE_FORCE
COMPLIANCE_FORCE_GAIN = 0.5  # controller_adapt.COMPLIANCE_FORCE_GAIN

# (yaw_offset_deg, center_align) -- controller_adapt._OBJECT_GRASP_META, object-shape
# properties reused as-is (gripper-independent).
OBJECT_GRASP_META: dict[str, tuple[float, bool]] = {
    "011_banana": (90.0, False),
    "014_lemon": (0.0, True),
    "018_plum": (0.0, True),
}


@dataclass(frozen=True)
class MjGraspProfile:
    yaw_offset_deg: float
    hand_to_fingertip: float
    close_force: float
    center_align: bool


def adapt_grasp_profile(params: GripperParams, pick_object: str) -> MjGraspProfile:
    yaw_offset, center_align = OBJECT_GRASP_META[pick_object]
    close_force = BASE_CLOSE_FORCE * (1.0 + COMPLIANCE_FORCE_GAIN * params.compliance)
    return MjGraspProfile(
        yaw_offset_deg=yaw_offset,
        hand_to_fingertip=hand_to_fingertip_z(params),
        close_force=close_force,
        center_align=center_align,
    )
