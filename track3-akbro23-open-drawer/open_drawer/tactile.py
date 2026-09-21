"""KinematicTaxel grids on both fingertips, and the two readings built on them.

Why this sensor sees the stop at all. KinematicTaxel is a spring-damper on
probe PENETRATION: normal force scales with how deep a probe is pressed into
whatever it touches, while the shear term is proportional to tangential
VELOCITY. At a hard stop the arm and the drawer both go still, so a grasp that
carried the pull load in shear would read its weakest exactly when the event
happens. The rail-and-gap handle exists to put that load on the pads as normal
force instead: the arm keeps commanding backward, the drawer cannot follow,
penetration climbs, and the reading ramps.

Two consumers, deliberately different:
  `feature`     flat (N, dim) for the dataset -- the whole field, unreduced,
                because the policy's encoder should decide what matters
  `peak_force`  (N,) scalar for the teacher's release trigger and the success
                test, which need a threshold rather than a field
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import genesis as gs
import genesis.utils.geom as gu

from .config import EnvConfig, TactileConfig

if TYPE_CHECKING:
    from genesis.engine.entities.rigid_entity import RigidEntity

FINGER_LINKS = ("left_finger", "right_finger")


def npy(x) -> np.ndarray:
    """Genesis tensor -> numpy, without assuming which it handed back."""
    return np.asarray(x.detach().cpu()) if hasattr(x, "detach") else np.asarray(x)


def probe_local_pos(tac: TactileConfig) -> np.ndarray:
    """(n_probes, 3) probe positions in the finger frame.

    Flattened rather than grid-shaped: KinematicTaxel takes a flat layout, and
    that is what makes its reading (..., n_probes, 3) instead of (..., ny, nx, 3).
    """
    return gu.generate_grid_points_on_plane(
        lo=tac.lo, hi=tac.hi, normal=tac.normal, nx=tac.nx, ny=tac.ny,
    ).reshape(-1, 3)


def add_sensors(scene: gs.Scene, franka: "RigidEntity", cfg: EnvConfig) -> list:
    """One taxel grid per fingertip. Must be called BEFORE scene.build()."""
    tac = cfg.tactile
    pos = probe_local_pos(tac)
    return [
        scene.add_sensor(gs.sensors.KinematicTaxel(
            entity_idx=franka.idx,
            link_idx_local=franka.get_link(name).idx_local,
            probe_local_pos=pos,
            probe_radius=tac.probe_radius,
            normal_stiffness=tac.normal_stiffness,
            normal_damping=tac.normal_damping,
            normal_exponent=tac.normal_exponent,
            shear_scalar=tac.shear_scalar,
            twist_scalar=tac.twist_scalar,
            draw_debug=cfg.show_viewer,
        ))
        for name in FINGER_LINKS
    ]


def forces(sensors: list, n_envs: int, n_probes: int) -> np.ndarray:
    """(N, 2, n_probes, 3) taxel force, fingers in FINGER_LINKS order.

    Genesis drops the batch dimension when the scene is unbatched, so the
    reshape is done from the tail rather than trusting the rank.
    """
    out = [npy(s.read().force).reshape(n_envs, n_probes, 3) for s in sensors]
    return np.stack(out, axis=1)


def feature(sensors: list, cfg: EnvConfig) -> np.ndarray:
    """(N, dim) float32 -- what the dataset stores as `observation.tactile`."""
    f = forces(sensors, cfg.n_envs, cfg.tactile.n_probes)
    return f.reshape(cfg.n_envs, -1).astype(np.float32)


def peak_force(sensors: list, cfg: EnvConfig) -> np.ndarray:
    """(N,) largest force magnitude over both fingers and every probe.

    The release threshold is set against this. It is a peak rather than a sum
    or a mean because the rail contacts a few probes out of eight, and an
    average dilutes the event by the probes that never touch anything.
    """
    f = forces(sensors, cfg.n_envs, cfg.tactile.n_probes)
    return np.linalg.norm(f, axis=-1).reshape(cfg.n_envs, -1).max(axis=1)
