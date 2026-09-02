"""LeRobot-compatible Gym environment wrapping RadeonHome Genesis pipeline.

Provides standard LeRobot env interface (reset, step) so lerobot-train /
lerobot-record can train ACT directly on AMD Radeon GPU.

Observation: RGB 224x224 (CHW uint8) + 16-D proprio
Action:      7-D delta (dx, dy, dz, dyaw, dgrip, grasp, place)
"""

from __future__ import annotations

import numpy as np
import gymnasium as gym
from gymnasium import spaces
from pathlib import Path


class RadeonHomeEnv(gym.Env):
    """Genesis mobile manipulation environment for imitation learning."""

    metadata = {"render_modes": ["rgb_array"], "render_fps": 15}

    def __init__(
        self,
        task: str = "trash_to_trash_bin",
        seed: int = 0,
        camera_res: tuple[int, int] = (224, 224),
        max_episode_steps: int = 500,
    ):
        super().__init__()
        self._task = task
        self._seed = seed
        self._camera_res = camera_res
        self._max_steps = max_episode_steps
        self._step_count = 0
        self._scene = None
        self._cam = None
        self._box = None
        self._done = False

        # Observation: RGB (3,224,224) CHW uint8 + proprio (16,) float32
        self.observation_space = spaces.Dict({
            "observation.images.cam_high": spaces.Box(
                0, 255, (3, *camera_res), dtype=np.uint8
            ),
            "observation.state": spaces.Box(
                -np.inf, np.inf, (16,), dtype=np.float32
            ),
        })

        # Action: delta (dx, dy, dz, dyaw, dgrip, grasp, place), all in [-1,1]
        self.action_space = spaces.Box(-1.0, 1.0, (7,), dtype=np.float32)

    def _build_scene(self):
        """Lazy-init a minimal Genesis scene on first reset."""
        if self._scene is not None:
            return

        import genesis as gs
        gs.init()
        scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=0.01, gravity=(0, 0, -9.81)),
            viewer_options=gs.options.ViewerOptions(
                res=self._camera_res, max_FPS=60
            ),
            show_viewer=False,
        )
        plane = scene.add_entity(gs.morphs.Plane())
        box = scene.add_entity(
            gs.morphs.Box(pos=(0, 0, 0.5), size=(0.05, 0.05, 0.05)),
            material=gs.materials.Rigid(),
        )
        cam = scene.add_camera(
            res=self._camera_res,
            pos=(1.5, 0.0, 2.0),
            lookat=(0, 0, 0.3),
            fov=48,
        )
        scene.build()
        self._scene = scene
        self._cam = cam
        self._box = box

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._build_scene()
        self._step_count = 0
        obs = self._get_obs()
        return obs, {"task": self._task}

    def _get_obs(self) -> dict:
        import torch
        rgb = self._cam.render(rgb=True)[0]
        # HWC uint8 -> CHW uint8
        img = np.transpose(rgb, (2, 0, 1)).astype(np.uint8)
        # 16-D proprio placeholder
        state = np.zeros(16, dtype=np.float32)
        return {
            "observation.images.cam_high": img,
            "observation.state": state,
        }

    def step(self, action):
        self._step_count += 1
        self._scene.step()
        obs = self._get_obs()
        terminated = self._step_count >= self._max_steps
        return obs, 0.0, terminated, False, {}

    def render(self):
        return self._cam.render(rgb=True)[0]

    def close(self):
        if self._scene is not None:
            import genesis as gs
            gs.destroy()
            self._scene = None
