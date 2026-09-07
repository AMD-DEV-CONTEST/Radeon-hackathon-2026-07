from __future__ import annotations

import numpy as np
import pytest

from radeonvla.physics import forbid_rigid_pose_writes, set_rigid_position, set_rigid_quaternion


class ModernEntity:
    def __init__(self) -> None:
        self.calls: list[tuple[str, np.ndarray, bool]] = []

    def set_pos(self, value, *, zero_velocity: bool = False) -> None:
        self.calls.append(("pos", np.asarray(value), zero_velocity))

    def set_quat(self, value, *, zero_velocity: bool = False) -> None:
        self.calls.append(("quat", np.asarray(value), zero_velocity))


class LegacyEntity:
    def __init__(self) -> None:
        self.zero_calls = 0

    def set_pos(self, value) -> None:
        self.pos = np.asarray(value)

    def set_quat(self, value) -> None:
        self.quat = np.asarray(value)

    def zero_all_dofs_velocity(self) -> None:
        self.zero_calls += 1


def test_modern_pose_setters_request_velocity_reset() -> None:
    entity = ModernEntity()
    set_rigid_position(entity, [1.0, 2.0, 3.0])
    set_rigid_quaternion(entity, [1.0, 0.0, 0.0, 0.0])
    assert entity.calls[0][0] == "pos" and entity.calls[0][2] is True
    assert entity.calls[1][0] == "quat" and entity.calls[1][2] is True


def test_legacy_pose_setters_explicitly_clear_velocity() -> None:
    entity = LegacyEntity()
    set_rigid_position(entity, [1.0, 2.0, 3.0])
    set_rigid_quaternion(entity, [1.0, 0.0, 0.0, 0.0])
    assert entity.zero_calls == 2


def test_strict_physics_guard_rejects_episode_pose_writes() -> None:
    entity = ModernEntity()
    with pytest.raises(RuntimeError, match="forbidden during strict physics recording"):
        with forbid_rigid_pose_writes():
            set_rigid_position(entity, [1.0, 2.0, 3.0])
    assert entity.calls == []

    # The context must restore normal reset-time pose writes afterward.
    set_rigid_position(entity, [1.0, 2.0, 3.0])
    assert len(entity.calls) == 1
