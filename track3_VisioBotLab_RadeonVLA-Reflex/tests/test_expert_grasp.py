from __future__ import annotations

import numpy as np

import radeonvla.expert as expert


class FakeFruit:
    def get_AABB(self):
        return np.array([[0.0, 0.0, 0.75], [0.06, 0.06, 0.81]])


def test_round_fruit_grasp_targets_equator() -> None:
    profile = expert.PROFILES["lemon"]
    hand_z = expert._grasp_hand_z(FakeFruit(), profile)
    fingertip_z = hand_z - expert.HAND_TO_FINGERTIP
    assert np.isclose(fingertip_z, 0.78)


def test_fruit_profiles_use_low_contact_force() -> None:
    assert all(-2.0 <= profile.close_force < 0.0 for profile in expert.PROFILES.values())
    assert all(profile.retry_drop == 0.0 for profile in expert.PROFILES.values())


def test_formal_collection_can_disable_kinematic_assist() -> None:
    assert "allow_kinematic_assist" in expert.run_pick_place.__annotations__
    assert "allow_kinematic_assist" in expert.run_resolved_task.__annotations__
