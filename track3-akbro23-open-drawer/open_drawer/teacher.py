"""Scripted demonstrator: open the drawer the prompt names, and let go of it.

Phases run in LOCKSTEP across envs. Every env executes the same phase for the
same number of steps; an env that releases early holds its last command rather
than dropping out. Async per-env phases would buy throughput the GPU spends
anyway, at the cost of ragged control flow through the whole stack.

The teacher may read simulator state -- it never ships. What it may NOT do is
emit actions the policy could not infer from what it sees. That is why the
release fires on the MEASURED taxel peak and never on the drawer's joint
position: the stop is invisible to every camera, so a teacher that let go on
privileged knowledge would pair identical observations with different correct
actions, and the release would be unlearnable.

Heights are measured to the gripper PAD CENTRE, not the fingertip. The pads run
up the inside of the fingers, 9.4 mm above their tips, so aiming the fingertip
at the rail centre pinches the rail by its top edge and lets it pivot out.
"""
from __future__ import annotations

import numpy as np

from . import robot, task_state
from .randomize import EpisodeSetup
from .scene import SceneBundle
from .task_state import EpisodeResult, Monitor


def pull_direction(b: SceneBundle) -> np.ndarray:
    """(N, 2) unit vector the drawer opens along, in world xy.

    The drawer slides along the cabinet's -x, which is only world -x when the
    cabinet is unrotated. Pulling along world -x on a yawed cabinet loads the
    slide sideways and racks it against its own joint.
    """
    yaw = b.setup.cabinet_yaw
    return np.stack([-np.cos(yaw), -np.sin(yaw)], axis=1)


def approach(b: SceneBundle, *, on_step=None) -> np.ndarray:
    """P1: hover over the target rail with the jaws open enough to straddle it."""
    t = b.cfg.teacher
    above = task_state.grasp_pos(b) + np.array([0.0, 0.0, t.approach_clear])
    return robot.move_to(b, above, fingers=t.q_open, max_dq=t.max_dq_transit,
                         settle=t.settle, on_step=on_step)


def descend(b: SceneBundle, setup: EpisodeSetup, *, on_step=None) -> np.ndarray:
    """P2: drop the jaws around the rail -- one finger in front, one behind it.

    Lands DELIBERATELY off-centre by `setup.descent_residual`. A teacher that
    always arrives centred produces a dataset with no corrections in it, and
    the policy then has nothing to imitate on the episodes where it arrives
    off.
    """
    t = b.cfg.teacher
    target = task_state.grasp_pos(b)
    target[:, :2] += setup.descent_residual
    return robot.servo_to(b, target, fingers=t.q_open, max_dq=t.max_dq_fine,
                          on_step=on_step)


def grip(b: SceneBundle, q_hold: np.ndarray, *, on_step=None) -> np.ndarray:
    """P3: squeeze the rail.

    The jaws are commanded THROUGH the rail. They cannot get there, so the
    standing position error times the finger `kp` is the grip force -- which is
    why FrankaConfig raises that gain. Commanding the rail's own thickness
    instead would arrive with no error and apply no force at all.
    """
    t = b.cfg.teacher
    q = robot.with_fingers(q_hold, t.q_grip, b.n_envs)
    robot.hold(b, q, t.grip_steps, on_step=on_step)
    return q


def pull(b: SceneBundle, rng: np.random.Generator, *, on_step=None) -> np.ndarray:
    """P4-P5: draw the drawer out until the stop is FELT, then let go.

    Every env ramps its hand target along the pull direction until its own
    taxel peak crosses the threshold. The drawer resists with a constant
    friction loss the whole way, so the reading is not zero before the stop --
    the threshold has to clear that steady load, which is why it is calibrated
    against a measured free pull rather than picked.

    Envs that have released freeze their hand and open their jaws while the
    rest keep pulling. Same lockstep, per-env branch, as everywhere else.
    """
    t, n = b.cfg.teacher, b.n_envs
    direction = pull_direction(b)

    hand = robot.hand_pos(b)
    xy_cmd, z_cmd = hand[:, :2].copy(), hand[:, 2].copy()
    released = np.zeros(n, dtype=bool)
    q_cmd = b.qpos()

    for _ in range(t.pull_steps):
        released |= b.tactile_peak() >= t.release_force

        step = direction * t.pull_rate + rng.normal(0.0, t.action_noise_xy, (n, 2))
        xy_cmd += step * (~released)[:, None]

        q = robot.solve_ik(b, np.c_[xy_cmd, z_cmd], fine=True)
        q = np.where(released[:, None], q_cmd, q)
        q = robot.with_fingers(q, np.where(released, t.q_open, t.q_grip), n)

        cmd = robot.apply(b, q)
        if on_step is not None:
            on_step(cmd)
        b.step()

        q_cmd = np.where(released[:, None], q_cmd, q)
        if released.all():
            break

    # Let the jaws finish opening before anything moves away.
    q_open = robot.with_fingers(q_cmd, t.q_open, n)
    robot.hold(b, q_open, t.release_steps, on_step=on_step)
    return q_open


def retract(b: SceneBundle, *, on_step=None) -> None:
    """P6: lift clear of the rail, jaws open.

    Straight up, and only then anything else: the fingers are still down inside
    the slot behind the rail, so any lateral move first would rake the drawer
    back or drag the cabinet -- either of which fails an episode the pull had
    already won.
    """
    t = b.cfg.teacher
    up = robot.hand_pos(b) + np.array([0.0, 0.0, t.retract_height])
    robot.move_to(b, up, fingers=t.q_open, max_dq=t.max_dq_transit,
                  settle=t.settle, on_step=on_step)


def run_episode(b: SceneBundle, setup: EpisodeSetup, rng: np.random.Generator, *,
                on_step=None) -> EpisodeResult:
    """One full demonstration across all envs. `b.reset(setup)` must precede."""
    monitor = Monitor(b)

    # The monitor watches EVERY control step of every phase, not just the pull.
    # Success has to hold for `hold_steps` consecutive steps, and the jaws only
    # finish opening after the pull loop has already broken -- so a monitor
    # updated inside `pull` alone never sees a released gripper, scores 0/8 on
    # episodes that did everything right, and dates the release to whenever it
    # was last polled, which turns latency into episode length.
    def tick(cmd) -> None:
        monitor.update()
        if on_step is not None:
            on_step(cmd)

    approach(b, on_step=tick)
    q = descend(b, setup, on_step=tick)
    grip(b, q, on_step=tick)
    pull(b, rng, on_step=tick)
    retract(b, on_step=tick)
    monitor.update()
    return monitor.result()
