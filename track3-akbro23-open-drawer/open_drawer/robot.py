"""Motion primitives: batched IK, velocity-limited moves, the control tick.

Everything here is batched and lockstep. Every env runs the same primitive for
the same number of steps -- a move takes `max` over envs of the steps each one
needs, and every env interpolates its own trajectory over that span. Async
per-env control would buy throughput the GPU spends anyway, at the cost of
ragged control flow through the whole stack.

A command is all nine joints. The fingers are position-controlled like every
other dof, which is what makes the action space a uniform 9-vector of joint
deltas -- no gripper mode riding alongside it. Grip force is then `kp` times
the commanded overshoot into the rail, which is why FrankaConfig raises the
finger `kp`: at the stock 100 the same overshoot is 0.45 N and the rail slips.
"""
from __future__ import annotations

import numpy as np
from genesis.utils.geom import euler_to_quat

from .scene import SceneBundle, npy

MOTORS = np.arange(7)
FINGERS = np.arange(7, 9)
N_DOFS = 9


def broadcast(x, n: int, width: int = 1) -> np.ndarray:
    """Coerce a scalar, (width,), (n,) or (n, width) command to (n, width).

    Finger commands arrive in every one of these shapes -- a scalar width, one
    per env, or an explicit pair -- and a bare reshape silently succeeds on
    some and raises on others.
    """
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 0:
        return np.full((n, width), float(a))
    if a.shape == (width,):
        return np.tile(a, (n, 1))
    if a.shape == (n,):
        return np.repeat(a[:, None], width, axis=1)
    if a.shape == (n, width):
        return a
    raise ValueError(f"cannot broadcast {a.shape} to ({n}, {width})")


def grasp_quat(b: SceneBundle, yaw: np.ndarray | None = None) -> np.ndarray:
    """(N, 4) tool-down orientation with the jaws square to the rail.

    `euler_to_quat` is roll-pitch-yaw in DEGREES, giving Rz(yaw) Ry(pitch)
    Rx(roll). Roll 180 points the tool axis at the table; yaw 90 carries the
    hand's y -- the axis the fingers travel along -- onto world x, so the jaws
    straddle the rail front-to-back rather than end-to-end. The cabinet's own
    yaw is added on top so a rotated cabinet is still approached square.
    """
    if yaw is None:
        yaw = np.zeros(b.n_envs) if b.setup is None else b.setup.cabinet_yaw
    euler = np.tile(np.asarray(b.cfg.franka.grasp_euler_deg, dtype=np.float64),
                    (b.n_envs, 1))
    euler[:, 2] += np.degrees(yaw)
    return euler_to_quat(euler)


def solve_ik(b: SceneBundle, pos: np.ndarray, quat: np.ndarray | None = None,
             *, fine: bool = False) -> np.ndarray:
    """(N, 3) target position -> (N, 9) joint targets.

    The finger entries of the result are whatever the solver left there and
    are meaningless; callers overwrite them. `fine=True` tightens the tolerance
    and drops the random restarts -- during the descent onto the rail the seed
    is already within a millimetre, so restarting from random configurations
    wastes time and can return a different arm configuration for a nearly
    identical target, which shows up as the wrist jumping between steps.
    """
    quat = grasp_quat(b) if quat is None else quat
    kw = dict(max_samples=1, max_solver_iters=8, pos_tol=1e-4) if fine else {}
    q = b.franka.inverse_kinematics(link=b.hand_link,
                                    pos=np.asarray(pos, dtype=np.float64),
                                    quat=np.asarray(quat, dtype=np.float64), **kw)
    return npy(q).reshape(b.n_envs, N_DOFS)


def with_fingers(q: np.ndarray, fingers, n: int) -> np.ndarray:
    """Replace an IK solution's finger entries with a commanded jaw position."""
    q = np.array(q, dtype=np.float64).reshape(n, N_DOFS)
    q[:, FINGERS] = broadcast(fingers, n, 2)
    return q


def apply(b: SceneBundle, qpos: np.ndarray) -> np.ndarray:
    """Command all nine joints. Returns the command actually issued, (N, 9).

    COMMANDS ARE ISSUED AT THE RECORDED RATE, not every control step. Between
    ticks this returns the command still in force and writes nothing, so the
    arm holds each target for `record_every` steps exactly as it will under a
    policy. The teacher is otherwise unchanged -- it still recomputes IK and
    closes its loops every step, so only the command rate drops.

    Without this the demonstrations and the deployment are different control
    problems: a recorded action would be one point off a 100 Hz ramp, while at
    inference that same number is held for 40 ms, so the arm reaches targets
    the ramp only passed through. `record_every` therefore sets the CONTROL
    tick, not just the storage rate.

    The recorded action is the COMMAND minus the measurement, never the motion
    that resulted. A position-controlled arm holding against gravity needs a
    permanent offset between the two, so training on achieved motion labels
    every hold "do nothing" -- and a policy obeying that at inference releases
    the offset holding the arm up and sags further every step.
    """
    if b.step_count % b.cfg.record_every and b.last_cmd is not None:
        return b.last_cmd

    q = np.asarray(qpos, dtype=np.float64).reshape(b.n_envs, N_DOFS)
    b.franka.control_dofs_position(q)
    b.last_cmd = q
    return q


def move_to(b: SceneBundle, pos: np.ndarray, quat: np.ndarray | None = None, *,
            fingers, max_dq: float = 0.010, settle: int = 0,
            fine: bool = False, on_step=None) -> np.ndarray:
    """Velocity-limited move to a cartesian target. Returns the final (N, 9).

    Interpolates in JOINT space from the current qpos to the IK solution, so no
    env exceeds `max_dq` radians per step on any joint. Commanding the IK
    solution directly makes the arm lunge, which can sweep the gripper through
    the rail on the way to it.
    """
    goal = with_fingers(solve_ik(b, pos, quat, fine=fine), fingers, b.n_envs)
    start = b.qpos()
    delta = goal - start

    # lockstep: every env takes the same number of steps, set by the worst case
    nsteps = max(int(np.ceil(np.abs(delta[:, MOTORS]).max() / max_dq)), 1)

    for i in range(1, nsteps + 1):
        cmd = apply(b, start + delta * (i / nsteps))
        # BEFORE the step, so the hook sees the state the command was issued
        # from rather than the one it produced. See `record.Recorder`.
        if on_step is not None:
            on_step(cmd)
        b.step()

    hold(b, goal, settle, on_step=on_step)
    return goal


def hold(b: SceneBundle, qpos: np.ndarray, steps: int, *, on_step=None) -> None:
    """Keep commanding the same target for `steps` steps."""
    for _ in range(steps):
        cmd = apply(b, qpos)
        if on_step is not None:
            on_step(cmd)
        b.step()


def servo_to(b: SceneBundle, pos: np.ndarray, quat: np.ndarray | None = None, *,
             fingers, iters: int = 3, settle: int = 40, tol: float = 3e-4,
             on_step=None, **move_kw) -> np.ndarray:
    """Move to a cartesian target, then CORRECT until the hand is really there.

    Open-loop IK-and-hold leaves millimetres of error from two independent
    causes: the IK solution is only solved to its tolerance, and position
    control droops -- holding the arm against gravity needs a torque, that
    torque is `kp` times a joint error, so a standing error is the equilibrium
    rather than a transient and more settling cannot remove it.

    So each iteration measures where the hand actually ended up and shifts the
    IK target by the shortfall -- integral action in cartesian space.
    """
    pos = np.asarray(pos, dtype=np.float64)
    move_kw.setdefault("fine", True)
    target, q = pos, None
    for _ in range(iters):
        q = move_to(b, target, quat, fingers=fingers, settle=settle,
                    on_step=on_step, **move_kw)
        err = pos - hand_pos(b)
        if np.linalg.norm(err, axis=1).max() < tol:
            break
        target = target + err
    return q


def hand_pos(b: SceneBundle) -> np.ndarray:
    return npy(b.hand_link.get_pos()).reshape(b.n_envs, 3)


def finger_width(b: SceneBundle) -> np.ndarray:
    """(N,) total jaw opening."""
    return b.qpos()[:, FINGERS].sum(axis=1)
