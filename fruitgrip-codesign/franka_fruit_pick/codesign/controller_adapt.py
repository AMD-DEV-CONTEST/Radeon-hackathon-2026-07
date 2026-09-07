"""Controller co-adaptation: derive a `sim_episode.GraspProfile` from a gripper design.

Project brief S5: "A fixed reward across changing bodies does not measure which body
is better. It measures which body best games the reward you wrote for a different
body." Two co-adaptation mechanisms live here, both *analytic* (zero extra sim cost,
always correct by construction) rather than a per-design nested search:

1. Grasp height: `hand_to_fingertip_z(params)` (gripper_gen.py) replaces the stock
   demo's constant `HAND_TO_FINGERTIP=0.105`. Skipping this is the single most direct
   way a copy-pasted fixed-reward pipeline would silently mis-score every non-default
   design -- it would command the fingertip to the *original* finger's reach depth
   regardless of the new one's actual length/curvature.
2. Grip force: scales with fingertip compliance, since a softer pad tolerates more
   closing force before damaging/ejecting the object -- this is what keeps a stiff
   2-finger design and a soft 3-finger design from being scored under the same force
   the way a blind fixed-reward pipeline would.

Object-dependent grasp *orientation* (yaw_offset, center_align) is a property of the
object's shape, not the gripper, so it is reused as-is from the stock demo's tuning
(`grasp_demo.GRASP_PROFILES`) rather than re-derived.

Deliberately NOT done here: a per-design local search over controller parameters
(e.g. CMA-ES-within-CMA-ES over close_force). That nested-search pattern is exactly
the "ruinous inner-loop cost" this project's brief (S2) identifies as the thing that
kept 20 years of co-design work on toy bodies. Instead, compliance is itself a
*searched* outer-loop parameter (gripper_gen.GripperParams.compliance) -- the population
search jointly discovers good (compliance, force-response) pairs rather than a nested
optimizer re-deriving force for each candidate from scratch.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from gripper_gen import GripperParams, hand_to_fingertip_z  # noqa: E402
from sim_episode import GraspProfile  # noqa: E402
import grasp_planner  # noqa: E402

BASE_CLOSE_FORCE = -10.0  # N, at compliance = 0 (rigid)
COMPLIANCE_FORCE_GAIN = 0.5  # allows up to 1.5x force at compliance = 1 (fully soft)

# Free/searchable controller parameters, for the attribution experiment (S7): "vary
# geometry with controller fixed" and "vary controller with geometry fixed" need an
# actual controller search space independent of geometry, not just the analytic
# geometry->controller rule below. `height_offset` is a small delta *on top of* the
# geometry-required fingertip reach -- the base `hand_to_fingertip_z(params)` term
# always still comes from the real geometry regardless of controller choice, because
# skipping it isn't "a worse controller," it's a broken IK target (S5.1's "gaming a
# reward that doesn't fit" trap, just inverted).
CLOSE_FORCE_BOUNDS = (-20.0, -5.0)
HEIGHT_OFFSET_BOUNDS = (-0.02, 0.02)


@dataclass(frozen=True)
class ControllerParams:
    close_force: float = -10.0
    height_offset: float = 0.0

    def clipped(self) -> "ControllerParams":
        return replace(
            self,
            close_force=float(np.clip(self.close_force, *CLOSE_FORCE_BOUNDS)),
            height_offset=float(np.clip(self.height_offset, *HEIGHT_OFFSET_BOUNDS)),
        )


BASELINE_CONTROLLER = ControllerParams(close_force=BASE_CLOSE_FORCE, height_offset=0.0)


def coadapted_controller(params: GripperParams) -> ControllerParams:
    """The analytic co-adaptation rule (compliance -> force) used by the joint search."""
    return ControllerParams(close_force=BASE_CLOSE_FORCE * (1.0 + COMPLIANCE_FORCE_GAIN * params.compliance), height_offset=0.0)

# (yaw_offset_deg, center_align) -- object-shape properties, reused from
# grasp_demo.GRASP_PROFILES's tuning (gripper-independent).
_OBJECT_GRASP_META: dict[str, tuple[float, bool]] = {
    "011_banana": (90.0, False),
    "014_lemon": (0.0, True),
    "018_plum": (0.0, True),
    "013_apple": (0.0, True),
    "017_orange": (0.0, True),
    "016_pear": (90.0, False),
    "025_mug": (0.0, False),
}
_DEFAULT_META = (90.0, False)


def adapt_grasp_profile(
    params: GripperParams, pick_object: str, controller: ControllerParams | None = None,
    *, use_planner: bool = False,
) -> GraspProfile:
    """`controller=None` (default): full analytic co-adaptation (compliance -> force),
    used by the joint co-design search. Pass an explicit `controller` -- e.g.
    `BASELINE_CONTROLLER` (geometry-only arm) or a swept `ControllerParams`
    (controller-only arm) -- to decouple the force/height choice from this design's
    own compliance, for the attribution experiment (run_attribution.py).

    `use_planner=False` (default): the original fixed per-object-name lookup
    (`_OBJECT_GRASP_META`, `sim_episode.GRASP_CENTER_DROP_FRAC`) -- byte-identical to
    every prior result in this project (confirmation-eval, attribution, cross-simulator,
    generalization). Every existing call site is unaffected by this flag's addition.

    `use_planner=True`: replace the height/yaw choice with `grasp_planner.plan_grasp`'s
    geometry-derived target for this exact (object, gripper aperture) pair. Falls back to
    the original fixed heuristic, per-object, whenever the planner reports the object as
    geometrically infeasible for this design at every sampled height/yaw -- a real
    "too big for this gripper" finding, not a bug to route around silently.
    """
    yaw_offset, center_align = _OBJECT_GRASP_META.get(pick_object, _DEFAULT_META)
    center_drop_frac = None
    if use_planner:
        planned = grasp_planner.plan_grasp(pick_object, params)
        if planned.feasible:
            yaw_offset = planned.yaw_offset_deg
            center_align = True
            center_drop_frac = planned.center_drop_frac
        # else: planner found no feasible grasp anywhere on this object for this design
        # -- keep the original fixed-heuristic (yaw_offset, center_align) as the fallback
        # rather than forcing an override we already know is infeasible.
    ctrl = (controller if controller is not None else coadapted_controller(params)).clipped()
    kwargs = dict(
        yaw_offset=yaw_offset,
        hand_to_fingertip=hand_to_fingertip_z(params) + ctrl.height_offset,
        close_force=ctrl.close_force,
        center_align=center_align,
    )
    if center_drop_frac is not None:
        kwargs["center_drop_frac"] = center_drop_frac
    return GraspProfile(**kwargs)
