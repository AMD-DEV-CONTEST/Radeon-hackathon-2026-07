"""Does the policy survive things it was never trained on?

Training randomises the command, nothing else. So every condition here except
`baseline` is off-distribution, which is the point: a locomotion policy that
only works on the surface it was trained on is not a useful one.

Each condition runs the same commands for the same duration and reports three
things: how often the robot stayed up, how well it tracked the command while it
was up, and what it scored. Survival alone would be a bad metric on its own,
because a policy that freezes in place never falls and never tracks anything,
so the tracking error is what stops that from looking like success.

One scene is built and reused across conditions, with each perturbation undone
afterwards. Rebuilding per condition would cost a minute of kernel compilation
each time and would risk the conditions not being otherwise identical.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import torch

from .env import Go2LocomotionEnv

CONDITIONS: dict[str, dict] = {
    "baseline": {},
    "payload_3kg": {"payload": 3.0},
    "payload_6kg": {"payload": 6.0},
    "friction_0.5": {"friction": 0.5},
    "friction_0.3": {"friction": 0.3},
    "friction_0.2": {"friction": 0.2},
    "push_0.5ms": {"push": 0.5},
    "push_1.0ms": {"push": 1.0},
}

#: Genesis resolves a contact pair by taking the LARGER of the two geoms'
#: friction values. Measured directly: robot 0.2 against plane 1.0 is
#: indistinguishable from baseline (survival 1.000, error 0.097 m/s), and so is
#: plane 0.2 against robot 1.0, while setting both to 0.2 drops survival to
#: 0.898 and triples tracking error. So a friction condition MUST set both
#: surfaces. Setting only the robot, which is the obvious thing to write, is a
#: silent no-op that quietly measures the baseline a second time.
FRICTION_NEEDS_BOTH_SURFACES = True


def _push(env: Go2LocomotionEnv, speed: float) -> None:
    """Shove the base sideways by overwriting its linear velocity DOFs."""
    n = env.num_envs
    vel = torch.zeros((n, 6), device=env.device)
    sign = torch.where(torch.rand(n, device=env.device) < 0.5, -1.0, 1.0)
    vel[:, 1] = sign * speed
    env.robot.set_dofs_velocity(vel, [0, 1, 2, 3, 4, 5])


@torch.no_grad()
def evaluate(
    env: Go2LocomotionEnv,
    policy,
    seconds: float = 10.0,
    push: float = 0.0,
    push_every_s: float = 2.0,
) -> dict:
    obs, _ = env.reset()
    steps = int(seconds / env.task.dt)
    push_every = int(push_every_s / env.task.dt)

    alive = torch.ones(env.num_envs, dtype=torch.bool, device=env.device)
    tracking_err = torch.zeros(env.num_envs, device=env.device)
    counted = torch.zeros(env.num_envs, device=env.device)
    returns = torch.zeros(env.num_envs, device=env.device)

    for i in range(steps):
        if push and i > 0 and i % push_every == 0:
            _push(env, push)
        obs, rew, done, extras = env.step(policy(obs))

        # A robot that has already fallen must not keep accruing credit, so
        # every metric below is masked by whether this env is still standing.
        fell = done & ~extras["time_outs"]
        alive &= ~fell
        err = torch.norm(env.commands[:, :2] - env.base_lin_vel[:, :2], dim=1)
        zero = torch.zeros_like(err)
        tracking_err += torch.where(alive, err, zero)
        counted += alive.float()
        returns += torch.where(alive, rew, zero)

    return {
        "survival_rate": round(float(alive.float().mean()), 4),
        "mean_tracking_error_ms": round(float((tracking_err / counted.clamp(min=1.0)).mean()), 4),
        "mean_return": round(float(returns.mean()), 3),
        "num_envs": env.num_envs,
        "seconds": seconds,
    }


def load_policy(checkpoint: str, env: Go2LocomotionEnv):
    """Load an rsl_rl checkpoint against an existing env, returning obs -> action.

    Takes the env rather than building one, because a Genesis scene costs about
    a minute of kernel compilation and both callers already have one.
    """
    from rsl_rl.runners import OnPolicyRunner

    from .train import train_config

    runner = OnPolicyRunner(env, train_config(1), log_dir=None, device=str(env.device))
    runner.load(checkpoint)
    return runner.get_inference_policy(device=env.device)


def run_all(
    checkpoint: str,
    num_envs: int = 512,
    out: str = "bench-results/robustness.json",
    seconds: float = 10.0,
) -> dict:
    import genesis as gs

    gs.init(backend=gs.amdgpu, logging_level="warning")
    env = Go2LocomotionEnv(num_envs=num_envs)
    policy = load_policy(checkpoint, env)

    trunk = env.robot.links[0]
    base_mass = float(trunk.get_mass())
    plane = env.scene.entities[0]
    rows = {}

    for name, kwargs in CONDITIONS.items():
        notes = []
        payload = kwargs.get("payload", 0.0)
        friction = kwargs.get("friction")
        if payload:
            trunk.set_mass(base_mass + payload)
            notes.append(f"trunk mass {base_mass:.2f} -> {float(trunk.get_mass()):.2f} kg")
        if friction is not None:
            env.robot.set_friction(friction)
            plane.set_friction(friction)
            notes.append(f"friction {friction} on both robot and ground")
        if kwargs.get("push"):
            notes.append(f"push {kwargs['push']} m/s every 2.0 s")

        t0 = time.time()
        row = evaluate(env, policy, seconds=seconds, push=kwargs.get("push", 0.0))
        row["notes"] = notes
        row["eval_seconds"] = round(time.time() - t0, 1)
        rows[name] = row
        print(
            f"{name:<14} survival={row['survival_rate']:.3f}  "
            f"tracking_err={row['mean_tracking_error_ms']:.3f} m/s  "
            f"return={row['mean_return']:.1f}",
            flush=True,
        )

        # Undo, so the next condition is not measured on a heavier or more
        # slippery robot than it asked for.
        if payload:
            trunk.set_mass(base_mass)
        if friction is not None:
            env.robot.set_friction(1.0)
            plane.set_friction(1.0)

    result = {
        "checkpoint": checkpoint,
        "base_trunk_mass_kg": round(base_mass, 3),
        "device": torch.cuda.get_device_properties(0).gcnArchName,
        "conditions": rows,
    }
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {p}")
    print("CHAAL_DONE")
    return result
