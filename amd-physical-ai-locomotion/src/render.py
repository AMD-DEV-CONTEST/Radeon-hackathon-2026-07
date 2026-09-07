"""Render a trained policy rollout to an mp4 for the 3-5 minute demo video.

Headless-friendly (MUJOCO_GL=osmesa). Produces outputs/videos/<env>.mp4.

Example:
    python -m src.render --env Go1JoystickFlatTerrain --steps 500
"""
from __future__ import annotations

import argparse

from src import config as C

C.set_headless_render_defaults()

import jax  # noqa: E402
import mediapy as media  # noqa: E402

from src.eval import load_env, load_inference_fn  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render a policy rollout to mp4.")
    p.add_argument("--env", default=C.DEFAULT_ENV)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--steps", type=int, default=500)
    p.add_argument("--ckpt", default=None)
    p.add_argument("--fps", type=int, default=None, help="Output fps (default: env control rate).")
    p.add_argument("--allow-cpu", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    C.ensure_dirs()
    C.assert_gpu(require=not args.allow_cpu)

    env_name = args.env
    env = load_env(env_name)
    ckpt_path = args.ckpt or (C.CKPT_DIR / f"{env_name}_seed{args.seed}.pkl")
    policy_fn = load_inference_fn(env, ckpt_path)

    jit_reset = jax.jit(env.reset)
    jit_step = jax.jit(env.step)
    jit_policy = jax.jit(policy_fn)

    rng = jax.random.PRNGKey(args.seed)
    state = jit_reset(rng)
    rollout = [state]
    for _ in range(args.steps):
        rng, akey = jax.random.split(rng)
        action = jit_policy(state.obs, akey)
        state = jit_step(state, action)
        rollout.append(state)
        if bool(state.done):
            state = jit_reset(rng)

    # env.render returns a list of RGB frames for the rollout of mjx states.
    frames = env.render([s for s in rollout])

    # Control dt: env physics dt * action_repeat (sim_dt exposed as env.dt).
    fps = args.fps or int(round(1.0 / float(env.dt)))
    out = C.VIDEO_DIR / f"{env_name}_seed{args.seed}.mp4"
    media.write_video(str(out), frames, fps=fps)
    print(f"[render] wrote {len(frames)} frames @ {fps}fps -> {out}")


if __name__ == "__main__":
    main()
