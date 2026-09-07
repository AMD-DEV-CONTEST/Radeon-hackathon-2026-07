"""Session 7: MuJoCo-side domain randomization, mirroring Genesis's randomize.py
Layer-B DR (friction_ratio_range, mass_ratio_range) at the *protocol* level -- same
ranges, same "sample once per trial, apply to the built scene" structure -- not a
bit-exact reproduction of Genesis's own mechanism (which isn't possible across
engines and isn't what the brief asks for: same DR ranges, not identical RNG draws).

Friction: Genesis scales a single shared ratio across YCB objects + Franka links +
table so the effective max()-based contact friction actually moves (see
randomize.py's DomainRandomizationConfig docstring). MuJoCo's own contact friction
combination rule is also elementwise-max over the two geoms' sliding coefficients, so
the same "scale every relevant surface by one shared ratio" approach produces the
same qualitative effect here.

Mass: Genesis scales each YCB object's mass by its own independently-sampled ratio
via set_mass_shift (mass only, robot mass fixed so tuned gains stay valid). Here we
scale both `body_mass` and `body_inertia` by the same ratio (rather than mass alone)
-- keeping the mass/inertia ratio fixed as geometry-consistent scaling would, which
is a defensible MuJoCo-side implementation choice, not a tuning knob chosen to
influence the result either direction.
"""
from __future__ import annotations

import numpy as np
import mujoco


def capture_base_friction(model, geom_ids: list[int]) -> dict[int, np.ndarray]:
    return {g: model.geom_friction[g].copy() for g in geom_ids}


def capture_base_mass(model, body_ids: list[int]) -> dict[int, tuple[float, np.ndarray]]:
    return {b: (float(model.body_mass[b]), model.body_inertia[b].copy()) for b in body_ids}


def apply_friction_ratio(model, base_friction: dict[int, np.ndarray], ratio: float) -> None:
    for g, base in base_friction.items():
        model.geom_friction[g] = base * np.array([ratio, 1.0, 1.0])  # only the sliding coeff scales


def apply_mass_ratio(model, base_mass: dict[int, tuple[float, np.ndarray]], body_id: int, ratio: float) -> None:
    base_m, base_i = base_mass[body_id]
    model.body_mass[body_id] = base_m * ratio
    model.body_inertia[body_id] = base_i * ratio


def franka_geom_ids(model, franka_contype: str = "1") -> list[int]:
    return [g for g in range(model.ngeom) if model.geom_contype[g] == int(franka_contype)]


def body_geom_ids(model, body_id: int) -> list[int]:
    return [g for g in range(model.ngeom) if model.geom_bodyid[g] == body_id]
