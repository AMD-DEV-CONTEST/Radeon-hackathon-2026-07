"""Interface tests independent of an installed Genesis runtime."""

import numpy as np

from simulation.genesis_env import GenesisPickPlaceEnv
from simulation.objects import PickPlaceObjects
from simulation.robot import FrankaRobot


class _Scene:
    def __init__(self):
        self.steps = 0

    def reset(self):
        self.steps = 0

    def step(self):
        self.steps += 1


class _Link:
    def get_pos(self):
        return [0.5, 0.0, 0.2]

    def get_quat(self):
        return [1.0, 0.0, 0.0, 0.0]


class _RobotEntity:
    def __init__(self):
        self.qpos = np.zeros(9, dtype=np.float32)

    def get_link(self, _name):
        return _Link()

    def set_qpos(self, value):
        self.qpos = np.asarray(value, dtype=np.float32)

    def control_dofs_position(self, value):
        self.qpos = np.asarray(value, dtype=np.float32)

    def get_dofs_position(self):
        return self.qpos

    def get_dofs_velocity(self):
        return np.zeros_like(self.qpos)


class _ObjectEntity:
    def __init__(self):
        self.position = np.zeros(3, dtype=np.float32)

    def set_pos(self, value, **_kwargs):
        self.position = np.asarray(value, dtype=np.float32)

    def get_pos(self):
        return self.position

    def get_quat(self):
        return [1.0, 0.0, 0.0, 0.0]

    def set_mass(self, _value):
        pass

    def set_friction(self, _value):
        pass


def test_gymnasium_reset_step_and_truncation():
    scene = _Scene()
    object_entity = _ObjectEntity()
    env = GenesisPickPlaceEnv(
        scene,
        FrankaRobot(_RobotEntity()),
        PickPlaceObjects(object_entity, [0.6, 0.0, 0.04], [0.4, 0.2, 0.04]),
        max_episode_steps=1,
    )
    observation, info = env.reset(seed=7)
    assert env.observation_space.contains(observation)
    assert info["episode_step"] == 0

    _, _, terminated, truncated, info = env.step(np.zeros(9, dtype=np.float32))
    assert not terminated
    assert truncated
    assert info["time_limit_reached"]
    assert scene.steps == env.control_decimation
