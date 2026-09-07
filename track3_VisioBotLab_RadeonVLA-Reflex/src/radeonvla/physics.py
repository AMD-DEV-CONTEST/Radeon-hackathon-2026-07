"""Small rigid-body helpers shared by reset and expert control paths."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_RIGID_POSE_WRITES_FORBIDDEN: ContextVar[bool] = ContextVar("rigid_pose_writes_forbidden", default=False)


@contextmanager
def forbid_rigid_pose_writes():
    """Fail closed if an object teleport is attempted during a strict rollout."""
    token = _RIGID_POSE_WRITES_FORBIDDEN.set(True)
    try:
        yield
    finally:
        _RIGID_POSE_WRITES_FORBIDDEN.reset(token)


def _assert_pose_write_allowed() -> None:
    if _RIGID_POSE_WRITES_FORBIDDEN.get():
        raise RuntimeError("Rigid-body pose writes are forbidden during strict physics recording")


def zero_rigid_velocity(entity: Any) -> None:
    """Clear all generalized velocities on a Genesis rigid entity."""
    zero = getattr(entity, "zero_all_dofs_velocity", None)
    if zero is not None:
        zero()


def set_rigid_position(entity: Any, pos) -> None:
    """Teleport a rigid entity without preserving stale linear/angular motion.

    Genesis ``RigidEntity.set_pos`` supports ``zero_velocity=True``.  The
    compatibility fallback keeps the helper usable with simple test doubles and
    older Genesis builds that expose only ``zero_all_dofs_velocity``.
    """
    _assert_pose_write_allowed()
    try:
        entity.set_pos(pos, zero_velocity=True)
    except TypeError:
        entity.set_pos(pos)
        zero_rigid_velocity(entity)


def set_rigid_quaternion(entity: Any, quat) -> None:
    """Set rigid orientation and clear generalized velocity."""
    _assert_pose_write_allowed()
    try:
        entity.set_quat(quat, zero_velocity=True)
    except TypeError:
        entity.set_quat(quat)
        zero_rigid_velocity(entity)
