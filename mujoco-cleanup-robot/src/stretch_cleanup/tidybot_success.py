"""Privileged TidyBot success labels for collection and offline evaluation.

This module reads MuJoCo object state and contacts.  Its outputs are labels, not
policy observations, and it must never be imported by a deployed policy path.
"""

from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np

from stretch_cleanup.mobile_platforms import BASKET_INNER_SIZE_M


LEFT_PAD_GEOMS = frozenset(("left_pad1", "left_pad2"))
RIGHT_PAD_GEOMS = frozenset(("right_pad1", "right_pad2"))


@dataclass(frozen=True)
class TidyBotSuccessSample:
    """One frame of privileged task evidence."""

    left_pad_contact: bool
    right_pad_contact: bool
    lift_m: float
    inside_basket: bool
    released: bool
    object_speed_mps: float

    @property
    def grasped_and_lifted(self) -> bool:
        return self.left_pad_contact and self.right_pad_contact and self.lift_m >= 0.06


def _named_geom_ids(model: mujoco.MjModel, names: frozenset[str]) -> set[int]:
    result: set[int] = set()
    for name in names:
        geom_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
        if geom_id >= 0:
            result.add(geom_id)
    return result


def gripper_contact_sides(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    object_name: str,
) -> tuple[bool, bool]:
    """Return whether the object currently touches each finger pad side."""

    object_body = model.body(object_name).id
    object_geoms = {
        geom_id
        for geom_id in range(model.ngeom)
        if int(model.geom_bodyid[geom_id]) == object_body
    }
    left_geoms = _named_geom_ids(model, LEFT_PAD_GEOMS)
    right_geoms = _named_geom_ids(model, RIGHT_PAD_GEOMS)
    left = right = False
    for contact in data.contact:
        pair = {int(contact.geom1), int(contact.geom2)}
        if not pair & object_geoms:
            continue
        left = left or bool(pair & left_geoms)
        right = right or bool(pair & right_geoms)
    return left, right


def object_in_cargo_basket(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    object_name: str,
    *,
    horizontal_margin_m: float = 0.012,
) -> bool:
    """Test object-centre containment in the moving basket's open cavity."""

    object_position = data.xpos[model.body(object_name).id]
    basket_id = model.body("cargo_basket").id
    basket_position = data.xpos[basket_id]
    basket_rotation = data.xmat[basket_id].reshape(3, 3)
    local = basket_rotation.T @ (object_position - basket_position)
    hx, hy, height = (
        BASKET_INNER_SIZE_M[0] / 2.0,
        BASKET_INNER_SIZE_M[1] / 2.0,
        BASKET_INNER_SIZE_M[2],
    )
    return bool(
        abs(float(local[0])) < hx - horizontal_margin_m
        and abs(float(local[1])) < hy - horizontal_margin_m
        and 0.024 < float(local[2]) < height
    )


def object_linear_speed(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    object_name: str,
) -> float:
    """Read translational speed of a free object in metres per second."""

    body_id = model.body(object_name).id
    joint_address = int(model.body_jntadr[body_id])
    if joint_address < 0 or model.jnt_type[joint_address] != mujoco.mjtJoint.mjJNT_FREE:
        return float(np.linalg.norm(data.cvel[body_id, 3:]))
    dof_address = int(model.jnt_dofadr[joint_address])
    return float(np.linalg.norm(data.qvel[dof_address : dof_address + 3]))


def object_pose_wxyz(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    object_name: str,
) -> np.ndarray:
    """Return privileged world position and quaternion for annotation only."""

    body_id = model.body(object_name).id
    return np.concatenate(
        (
            np.asarray(data.xpos[body_id], dtype=np.float32),
            np.asarray(data.xquat[body_id], dtype=np.float32),
        )
    )


def object_height_m(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    object_name: str,
) -> float:
    return float(data.xpos[model.body(object_name).id, 2])


def sample_success(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    object_name: str,
    *,
    initial_height_m: float,
) -> TidyBotSuccessSample:
    left, right = gripper_contact_sides(model, data, object_name)
    height = float(data.xpos[model.body(object_name).id, 2])
    return TidyBotSuccessSample(
        left_pad_contact=left,
        right_pad_contact=right,
        lift_m=height - initial_height_m,
        inside_basket=object_in_cargo_basket(model, data, object_name),
        released=not left and not right,
        object_speed_mps=object_linear_speed(model, data, object_name),
    )


@dataclass
class DepositStabilityTracker:
    """Require a released object to remain settled inside the basket."""

    required_seconds: float = 0.5
    maximum_speed_mps: float = 0.04
    stable_seconds: float = 0.0

    def update(self, sample: TidyBotSuccessSample, dt: float) -> bool:
        if dt <= 0.0:
            raise ValueError("dt must be positive")
        stable = (
            sample.inside_basket
            and sample.released
            and sample.object_speed_mps <= self.maximum_speed_mps
        )
        self.stable_seconds = self.stable_seconds + dt if stable else 0.0
        return self.stable_seconds + 1e-9 >= self.required_seconds

    def reset(self) -> None:
        self.stable_seconds = 0.0
