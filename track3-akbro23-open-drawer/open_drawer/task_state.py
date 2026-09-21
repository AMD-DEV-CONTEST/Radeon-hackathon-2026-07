"""Where the drawer and cabinet are, and whether the episode succeeded.

Privileged and measured are kept apart on purpose.

`at_stop` reads the drawer's joint position against the stop this episode
sampled. Nothing outside the simulator can know that -- no camera sees how far
a closed drawer will open -- so the teacher never triggers on it. It exists to
SCORE: `latency` is the gap between the true stop and the release the tactile
threshold actually fired, and that number is what shows touch is doing work
rather than merely being present.

Success needs the cabinet to have stayed put. It stands free on the table, so a
policy that ignores the stop and keeps pulling drags the furniture toward
itself -- that is the cost that makes releasing on the felt stop necessary. A
run that opens the drawer by shoving the cabinet has not done the task.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from genesis.utils.geom import quat_to_R

from .config import SIDES
from .scene import SceneBundle, npy

FINGERS = np.arange(7, 9)


def rail_pos(b: SceneBundle) -> np.ndarray:
    """(N, 2, 3) world centre of each drawer's rail, in SIDES order.

    Read from the drawer LINK rather than computed from the episode's cabinet
    pose, because the rail moves: it rides out with the drawer as it opens, and
    the pull has to keep tracking it.
    """
    out = np.empty((b.n_envs, len(SIDES), 3), dtype=np.float64)
    local = np.array([b.cfg.cabinet.rail_x, 0.0, b.cfg.cabinet.rail_z])
    for k, link in enumerate(b.drawer_links):
        pos = npy(link.get_pos()).reshape(b.n_envs, 3)
        R = quat_to_R(npy(link.get_quat()).reshape(b.n_envs, 4))
        out[:, k, :] = pos + R @ local
    return out


def target_rail(b: SceneBundle) -> np.ndarray:
    """(N, 3) rail centre of the drawer the prompt named."""
    return rail_pos(b)[np.arange(b.n_envs), b.setup.target_idx]


def grasp_pos(b: SceneBundle) -> np.ndarray:
    """(N, 3) hand position that centres the PADS on the target rail.

    Measured to the pad centre, not the fingertip. The Panda's pads run up the
    inside of the fingers, 9.4 mm above their tips, so aiming the fingertip at
    the rail centre would put the pads that far high and pinch it by its top
    edge.
    """
    return target_rail(b) + np.array([0.0, 0.0, b.cfg.franka.hand_to_pad])


def jaw_width(b: SceneBundle) -> np.ndarray:
    """(N,) total jaw opening."""
    return b.qpos()[:, FINGERS].sum(axis=1)


def cabinet_shift(b: SceneBundle) -> np.ndarray:
    """(N,) how far the cabinet has slid horizontally from where it spawned."""
    return np.linalg.norm(b.cabinet_pos()[:, :2] - b.setup.cabinet_pos[:, :2], axis=1)


def at_stop(b: SceneBundle) -> np.ndarray:
    """(N,) PRIVILEGED: the target drawer has reached this episode's stop."""
    rows = np.arange(b.n_envs)
    travel = b.drawer_travel()[rows, b.setup.target_idx]
    return travel >= b.setup.target_travel - b.cfg.success.open_eps


def state(b: SceneBundle) -> dict:
    """Per-env task state. Arrays over envs.

    travel        (N,) target drawer's travel
    opened        (N,) it reached this episode's stop
    other_travel  (N,) the distractor drawer's travel
    other_closed  (N,) the distractor never moved
    released      (N,) jaws open AND no residual contact
    shift         (N,) cabinet displacement
    cabinet_ok    (N,) it stayed put
    done          (N,) every criterion at once
    """
    s = b.cfg.success
    rows = np.arange(b.n_envs)
    tgt = b.setup.target_idx

    all_travel = b.drawer_travel()
    travel = all_travel[rows, tgt]
    other_travel = all_travel[rows, 1 - tgt]

    opened = travel >= b.setup.target_travel - s.open_eps
    other_closed = other_travel <= s.closed_eps
    # Both halves matter: jaws far enough apart to be off the rail, and no
    # force left on the pads. Width alone passes while the rail is still
    # pinched by a jammed finger.
    released = (jaw_width(b) >= s.release_width) & (b.tactile_peak() <= s.release_force)
    shift = cabinet_shift(b)
    cabinet_ok = shift <= s.cabinet_shift_max

    return {
        "travel": travel, "opened": opened,
        "other_travel": other_travel, "other_closed": other_closed,
        "released": released, "shift": shift, "cabinet_ok": cabinet_ok,
        "done": opened & other_closed & released & cabinet_ok,
    }


@dataclass
class EpisodeResult:
    success: np.ndarray        # (N,) every criterion, held
    opened: np.ndarray         # (N,) reached the stop
    released: np.ndarray       # (N,)
    wrong_drawer: np.ndarray   # (N,) the distractor moved
    dragged: np.ndarray        # (N,) the cabinet was shoved
    travel: np.ndarray         # (N,) final travel, m
    shortfall: np.ndarray      # (N,) stop minus travel, m
    shift: np.ndarray          # (N,) final cabinet displacement, m
    latency: np.ndarray        # (N,) control steps from true stop to release

    @property
    def n(self) -> int:
        return len(self.success)


class Monitor:
    """Latches success and times the release. Updated once per control step.

    Success is latched over `hold_steps` consecutive passes. A single-step test
    flickers -- it can pass while the drawer is still settling and fail on the
    next step, which reads as success in a log and as flicker in a video.

    The two step counters are the point of this class. `stop_step` is when the
    drawer actually hit its limit; `release_step` is when the gripper actually
    let go. Their difference is what the tactile channel is judged on.
    """

    def __init__(self, b: SceneBundle):
        self.b = b
        n = b.n_envs
        self.need = b.cfg.success.hold_steps
        self.count = np.zeros(n, dtype=np.int32)
        self.confirmed = np.zeros(n, dtype=bool)
        self.gripped = np.zeros(n, dtype=bool)
        self.stop_step = np.full(n, -1, dtype=np.int32)
        self.release_step = np.full(n, -1, dtype=np.int32)

    def update(self) -> dict:
        st = state(self.b)
        step = self.b.step_count

        first = (self.stop_step < 0) & at_stop(self.b)
        self.stop_step = np.where(first, step, self.stop_step)

        # "Released" only means something once something was HELD. The test is
        # jaws-open-and-no-contact, which is equally true of an empty gripper
        # at step 0 -- so without this gate every episode dates its release to
        # the approach and reports a negative latency.
        self.gripped |= self.b.tactile_peak() > self.b.cfg.success.release_force
        first = (self.release_step < 0) & self.gripped & st["released"]
        self.release_step = np.where(first, step, self.release_step)

        self.count = np.where(st["done"], self.count + 1, 0)
        self.confirmed |= self.count >= self.need
        st["confirmed"] = self.confirmed.copy()
        return st

    def latency(self) -> np.ndarray:
        """(N,) control steps between the true stop and the release.

        -1 marks an env where one of the two never happened. A negative
        difference would mean letting go before the drawer stopped, which is a
        failure to open rather than a fast reaction.
        """
        both = (self.stop_step >= 0) & (self.release_step >= 0)
        return np.where(both, self.release_step - self.stop_step, -1)

    def result(self) -> EpisodeResult:
        st = state(self.b)
        return EpisodeResult(
            # Confirmed AND still true: either alone counts a transient as a pass.
            success=self.confirmed & st["done"],
            opened=st["opened"], released=st["released"],
            wrong_drawer=~st["other_closed"], dragged=~st["cabinet_ok"],
            travel=st["travel"],
            shortfall=self.b.setup.target_travel - st["travel"],
            shift=st["shift"], latency=self.latency(),
        )
