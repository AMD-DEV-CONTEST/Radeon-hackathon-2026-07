#!/usr/bin/env python3
"""Train a Go1 joystick locomotion policy with brax PPO on this instance.

The AMD Radeon GPU is blocked by a ROCm profiler race (see docs/ROCM_BUG_REPORT.md),
so JAX falls back to CPU. This trains anyway — just slower. Checkpoints are written
periodically to CKPT_DIR so the demo can render from the latest one at any time,
even before training finishes.

Usage (on the instance):
    cd /workspace/demo
    MUJOCO_GL=egl nohup python3 scripts/train_go1.py > train.log 2>&1 &
    tail -f train.log          # watch progress; reward should climb
"""
import os
import time
import pickle
import functools
from pathlib import Path

import jax
import jax.numpy as jnp

# --- shim: JAX 0.11 removed device_put_replicated; brax 0.14.2 still calls it.
# CPU has a single device, so a plain stack + device_put is equivalent. -------
if not hasattr(jax, "device_put_replicated"):
    def _dpr(x, devices):
        n = len(devices)
        stacked = jax.tree_util.tree_map(
            lambda l: jnp.broadcast_to(jnp.asarray(l), (n,) + jnp.asarray(l).shape), x)
        if n == 1:
            return jax.device_put(stacked, devices[0])
        return jax.device_put_sharded(
            [jax.tree_util.tree_map(jnp.asarray, x)] * n, devices)
    jax.device_put_replicated = _dpr
# ---------------------------------------------------------------------------

from mujoco_playground import registry, wrapper
from mujoco_playground.config import locomotion_params
from brax.training.agents.ppo import train as ppo
from brax.training.agents.ppo import networks as ppo_networks

ENV = "Go1JoystickFlatTerrain"
TOTAL_STEPS = int(os.environ.get("TRAIN_STEPS", 40_000_000))
NUM_ENVS = int(os.environ.get("TRAIN_ENVS", 1024))
CKPT_DIR = Path("checkpoints"); CKPT_DIR.mkdir(exist_ok=True)


def main():
    print(f"[train] jax devices: {jax.devices()}", flush=True)
    print(f"[train] env={ENV} total_steps={TOTAL_STEPS} num_envs={NUM_ENVS}", flush=True)

    cfg = registry.get_default_config(ENV)
    cfg.impl = "jax"                        # force JAX-MJX (no Warp/GPU)
    env = registry.load(ENV, config=cfg)

    ppo_params = locomotion_params.brax_ppo_config(ENV)
    ppo_params.num_timesteps = TOTAL_STEPS
    ppo_params.num_envs = NUM_ENVS
    ppo_params.num_evals = max(2, TOTAL_STEPS // 2_000_000)   # ckpt every ~2M steps

    kw = dict(ppo_params)
    nf = kw.pop("network_factory", None)
    network_factory = (functools.partial(ppo_networks.make_ppo_networks, **nf)
                       if nf else ppo_networks.make_ppo_networks)

    t0 = time.time()

    def progress(step, metrics):
        r = metrics.get("eval/episode_reward")
        rl = metrics.get("eval/episode_reward_std")
        dt = time.time() - t0
        sps = step / dt if dt > 0 else 0
        print(f"[train] step={step:>10}  reward={r}  std={rl}  "
              f"elapsed={dt/60:.1f}min  {sps:.0f} steps/s", flush=True)

    def save_ckpt(step, make_policy, params):
        path = CKPT_DIR / f"go1_{int(step)}.pkl"
        with open(path, "wb") as f:
            pickle.dump(params, f)
        # keep a stable 'latest' pointer for the renderer
        with open(CKPT_DIR / "latest.pkl", "wb") as f:
            pickle.dump(params, f)
        print(f"[train] saved checkpoint {path}", flush=True)

    train_fn = functools.partial(
        ppo.train, **kw,
        network_factory=network_factory,
        wrap_env_fn=wrapper.wrap_for_brax_training,
        randomization_fn=registry.get_domain_randomizer(ENV),
        progress_fn=progress,
        policy_params_fn=save_ckpt,
    )

    make_inference_fn, params, _ = train_fn(environment=env)

    with open(CKPT_DIR / "final.pkl", "wb") as f:
        pickle.dump(params, f)
    print(f"[train] DONE in {(time.time()-t0)/60:.1f} min. "
          f"Final params -> {CKPT_DIR/'final.pkl'}", flush=True)


if __name__ == "__main__":
    main()
