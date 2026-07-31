"""Per-episode reset randomization for the color-sorting scene.

Based on franka_fruit_pick_demo's randomize.py. Key changes:
- RELIABLE_PICK_POOL = all color_geometry object names (not YCB names)
- Home positions derived from OBJECT_LAYOUT (not YCB_LAYOUT)
- No domain randomization (DR) for Phase A — keep it simple, add later
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from genesis.utils.geom import euler_to_quat

from scene_config import (
    COLORS,
    FRANKA_QPOS,
    GEOMETRIES,
    PICKABLE_GEOMETRIES,
    OBJECT_LAYOUT,
    OBJECT_SIZE,
    REACH_X,
    REACH_Y,
    TABLE_TOP_Z,
    object_rest_z_offset,
)


@dataclass
class RandomizationConfig:
    """Knobs for one episode's randomization."""

    pos_jitter: float = 0.03  # +/- m, uniform box around each object's home slot
    yaw_jitter: float = 30.0  # +/- deg around each object's home yaw
    randomize_pick: bool = True  # sample the pick object from the pool
    settle_steps: int = 80
    success_tol: float = 0.06
    seed: int | None = None


# All objects are pickable (small uniform primitives, unlike demo's mixed YCB)
def get_pick_pool(colors: tuple[str, ...] = COLORS) -> tuple[str, ...]:
    """Return all pickable object names for the given colors.

    Only cube + cylinder are pickable (spheres excluded — parallel-jaw
    gripper cannot reliably hold smooth spheres, same as demo's exclusion
    of apple/orange/pear).
    """
    return tuple(f"{color}_{geom}" for color in colors for geom in PICKABLE_GEOMETRIES)


class EnvRandomizer:
    """Resets a built SortSceneBundle to a fresh, randomized sorting episode."""

    def __init__(self, bundle, config: RandomizationConfig | None = None):
        self.bundle = bundle
        self.cfg = config or RandomizationConfig()
        self.rng = np.random.default_rng(self.cfg.seed)

        self.names = list(bundle.objects.keys())
        # Home positions from OBJECT_LAYOUT
        self.home = {}
        self.home_yaw = {}
        for name in self.names:
            color, geometry = name.rsplit("_", 1)
            x, y = OBJECT_LAYOUT[color][geometry]
            self.home[name] = np.asarray([x, y], dtype=float)
            self.home_yaw[name] = 0.0  # all objects start with yaw=0

    def reset(self, seed: int | None = None) -> str:
        """Randomize object poses and settle physics. Returns the pick object name."""
        if seed is not None:
            self.rng = np.random.default_rng(seed)

        self._reset_robot()
        self._place_objects()
        self._settle()
        return self._sample_pick()

    def _reset_robot(self) -> None:
        q = np.asarray(FRANKA_QPOS, dtype=float)
        self.bundle.franka.set_qpos(q, zero_velocity=True)

    def _place_objects(self) -> None:
        for name in self.names:
            # Small jitter around home position
            dx, dy = self.rng.uniform(-self.cfg.pos_jitter, self.cfg.pos_jitter, size=2)
            x = float(np.clip(self.home[name][0] + dx, *REACH_X))
            y = float(np.clip(self.home[name][1] + dy, *REACH_Y))

            # Derive z from geometry
            color, geometry = name.rsplit("_", 1)
            z = TABLE_TOP_Z + object_rest_z_offset(geometry) + 0.002

            # Yaw jitter
            dyaw = float(self.rng.uniform(-self.cfg.yaw_jitter, self.cfg.yaw_jitter))
            quat = euler_to_quat(np.array([0.0, 0.0, dyaw]))

            entity = self.bundle.objects[name]
            entity.set_pos(
                np.array([x, y, z]),
                relative=False, zero_velocity=True, skip_forward=True,
            )
            entity.set_quat(
                quat, relative=False, zero_velocity=True, skip_forward=False,
            )

    def _settle(self) -> None:
        hold = np.asarray(FRANKA_QPOS, dtype=float)
        for _ in range(self.cfg.settle_steps):
            self.bundle.franka.control_dofs_position(hold)
            self.bundle.scene.step()
            self.bundle.update_wrist_cam()

    def _sample_pick(self) -> str:
        pool = list(self.bundle.objects.keys())
        if not pool:
            raise RuntimeError("No objects present in the scene.")
        if self.cfg.randomize_pick:
            return str(self.rng.choice(pool))
        return pool[0]


def main() -> None:
    import argparse

    import genesis as gs

    from build_scene import build_scene
    from sk_grasp_demo import TaskSpec, run_pick_place

    parser = argparse.ArgumentParser(description="Randomized sorting episodes.")
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("-c", "--cpu", action="store_true", default=False)
    parser.add_argument("-n", "--episodes", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--jitter", type=float, default=0.03)
    args = parser.parse_args()

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(show_viewer=args.vis)
    cfg = RandomizationConfig(pos_jitter=args.jitter, seed=args.seed)
    randomizer = EnvRandomizer(bundle, cfg)

    n_success = 0
    for ep in range(args.episodes):
        episode_seed = args.seed + ep
        pick_object = randomizer.reset(seed=episode_seed)
        task = TaskSpec(
            pick_object=pick_object,
            place_target=TaskSpec(pick_object=pick_object, place_target="").pick_color,
        )
        success, _ = run_pick_place(bundle, task)
        n_success += int(success)
        print(
            f"[randomize] ep {ep:03d} seed={episode_seed} "
            f"pick={pick_object} -> success={success}"
        )

    print(f"[randomize] {n_success}/{args.episodes} succeeded")


if __name__ == "__main__":
    main()