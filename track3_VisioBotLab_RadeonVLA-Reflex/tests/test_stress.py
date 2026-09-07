from dataclasses import dataclass, field

import numpy as np

from radeonvla.stress import inject_perturbation, shifted_position


class Entity:
    def __init__(self) -> None:
        self.pos = np.array([0.1, 0.2, 0.3])

    def get_pos(self):
        return self.pos

    def set_pos(self, pos, zero_velocity=False) -> None:
        self.pos = np.asarray(pos)


@dataclass
class Goal:
    object_name: str = "banana"
    container: str = "white_left_bowl"


@dataclass
class Resolved:
    goals: tuple[Goal, ...] = field(default_factory=lambda: (Goal(),))


class Bundle:
    def __init__(self) -> None:
        self.objects = {"banana": Entity(), "white_left_bowl": Entity()}


def test_shifted_position_is_deterministic_and_preserves_z() -> None:
    a = shifted_position([0.0, 0.0, 0.3], distance=0.05, seed=7)
    b = shifted_position([0.0, 0.0, 0.3], distance=0.05, seed=7)
    assert np.allclose(a, b)
    assert np.isclose(np.linalg.norm(a[:2]), 0.05)
    assert a[2] == 0.3


def test_inject_target_shift_moves_expected_entity() -> None:
    bundle = Bundle()
    bowl_before = bundle.objects["white_left_bowl"].pos.copy()
    event = inject_perturbation(
        bundle,
        Resolved(),
        kind="target_shift",
        distance=0.05,
        seed=3,
        step=20,
    )
    assert event is not None
    assert event["entity"] == "banana"
    assert not np.allclose(bundle.objects["banana"].pos[:2], [0.1, 0.2])
    assert np.allclose(bundle.objects["white_left_bowl"].pos, bowl_before)
