"""Train a BeyondMimic-style whole-body tracking policy (MJX + Brax PPO, ROCm).

Hyperparameters follow BeyondMimic's rsl_rl_ppo_cfg.py where possible:
    networks [512,256,128], entropy 0.005, gamma 0.99, lam 0.95, clip 0.2
Two deviations are forced by the platform and the framework:
    1. a fixed learning rate — brax PPO has no adaptive-KL schedule
    2. num_minibatches x num_updates_per_batch <= 32 — the XLA graph-size
       ceiling on gfx1100, above which code generation segfaults (128 is
       reliably fatal)
"""

import argparse
import functools
import json
import time
from pathlib import Path

import jax
import numpy as np

# ---- compatibility shim for brax on JAX 0.11 -------------------------
# brax 0.14.2 still calls jax.device_put_replicated, removed in JAX 0.11 with
# the pmap migration. NVIDIA users can downgrade JAX to work around it; AMD
# users cannot, because the JAX version is pinned by jax-rocm7-plugin and
# downgrading loses the GPU entirely.
if not hasattr(jax, "device_put_replicated"):
    import jax.numpy as jnp

    def _dpr(x, devices):
        n = len(devices)
        stacked = jax.tree_util.tree_map(lambda y: jnp.stack([jnp.asarray(y)] * n), x)
        return jax.device_put(stacked, devices[0]) if n == 1 else stacked

    jax.device_put_replicated = _dpr
    print("[patch] injected jax.device_put_replicated compatibility shim", flush=True)

from brax.training.agents.ppo import networks as ppo_networks  # noqa: E402
from brax.training.agents.ppo import train as ppo  # noqa: E402
from flax.training import orbax_utils  # noqa: E402
from orbax import checkpoint as ocp  # noqa: E402

from mujoco_playground import wrapper  # noqa: E402

import g1_track  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--motion", required=True)
    ap.add_argument("--run_name", required=True)
    ap.add_argument("--out_root", default=None,
                    help="where run directories go "
                         "(default: workdir/train)")
    ap.add_argument("--num_envs", type=int, default=4096)
    ap.add_argument("--num_timesteps", type=int, default=300_000_000)
    ap.add_argument("--num_evals", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--domain_rand", action="store_true")
    ap.add_argument("--no_penalty", action="store_true",
                    help="ablation: disable action_rate and joint_limit penalties")
    ap.add_argument("--entropy", type=float, default=1e-3)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--keep_checkpoints", action="store_true",
                    help="also save a step-numbered checkpoint at every evaluation")
    args = ap.parse_args()

    print("=" * 60)
    print(f"JAX: {jax.default_backend()} {jax.devices()}")
    print("=" * 60)

    # Absolute by default. This used to be a relative "output/train", which
    # landed wherever the caller happened to be: the webapp runs this with
    # cwd=src/, so hours of checkpoints went to src/output/train while every
    # reader — the webapp, verify.sh, the run dropdown — looked in
    # workdir/train and reported that training had produced nothing.
    if args.out_root:
        out = Path(args.out_root) / args.run_name
    else:
        import config as _cfg
        out = _cfg.TRAIN_OUT / args.run_name
    out.mkdir(parents=True, exist_ok=True)
    print(f"[train] checkpoints -> {out}")

    cfg = g1_track.default_config()
    if args.no_penalty:
        cfg.reward_config.scales.action_rate = 0.0
        cfg.reward_config.scales.joint_limit = 0.0
        print("[ablation] action_rate and joint_limit penalties disabled")
    env = g1_track.G1Track(args.motion, config=cfg)
    eval_env = g1_track.G1Track(args.motion, config=cfg)

    randomizer = None
    if args.domain_rand:
        import randomize_ext
        randomizer = randomize_ext.domain_randomize
        print("[train] extended domain randomisation enabled")

    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(512, 256, 128),
        value_hidden_layer_sizes=(512, 256, 128),
        policy_obs_key="state",
        value_obs_key="privileged_state",
    )

    hist = []
    best = [-1e18]
    t0 = time.time()

    # TensorBoard, written next to the checkpoints. tensorboardX rather than
    # torch.utils.tensorboard: this venv deliberately has no torch (it would
    # drag in a second numpy), and tensorboardX is a standalone event writer.
    try:
        from tensorboardX import SummaryWriter
        tb = SummaryWriter(str(out / "tb"))
    except Exception as e:                                   # noqa: BLE001
        print(f"[train] no TensorBoard logging: {e}", flush=True)
        tb = None

    def progress(step, metrics):
        el = time.time() - t0
        rew = float(metrics.get("eval/episode_reward", 0.0))
        eplen = float(metrics.get("eval/avg_episode_length", 0.0))
        e_bp = float(metrics.get("eval/episode_err_body_pos", 0.0))
        e_bo = float(metrics.get("eval/episode_err_body_ori", 0.0))
        # These two are episode totals; divide by length for a per-step mean.
        n = max(eplen, 1.0)
        rec = {"t": el, "step": int(step), "reward": rew, "ep_len": eplen,
               "err_body_pos_m": e_bp / n, "err_body_ori_rad": e_bo / n}
        hist.append(rec)
        print(f"[{el:7.1f}s] step={step:>12,}  reward={rew:8.2f}  "
              f"ep_len={eplen:7.1f}  body_pos={e_bp/n:.4f}m  "
              f"body_ori={e_bo/n:.4f}rad  "
              f"{int(step/max(el,1e-9)):,} steps/s", flush=True)
        (out / "history.json").write_text(json.dumps(hist, indent=2))
        if tb is not None:
            tb.add_scalar("reward/episode", rew, step)
            tb.add_scalar("reward/episode_length", eplen, step)
            tb.add_scalar("error/body_position_m", e_bp / n, step)
            tb.add_scalar("error/body_orientation_rad", e_bo / n, step)
            tb.add_scalar("throughput/env_steps_per_s",
                          step / max(el, 1e-9), step)
            # Flush every eval: the page is watched live while training runs.
            tb.flush()

    def policy_params_fn(step, make_policy, params):
        del make_policy
        rew = hist[-1]["reward"] if hist else -1e18
        ck = ocp.PyTreeCheckpointer()
        ck.save(out.absolute() / "params_latest",
                params, force=True,
                save_args=orbax_utils.save_args_from_target(params))
        if rew > best[0]:
            best[0] = rew
            ck.save(out.absolute() / "params_best",
                    params, force=True,
                    save_args=orbax_utils.save_args_from_target(params))
            print(f"    -> new best reward={rew:.2f}", flush=True)
        if args.keep_checkpoints:
            ck.save(out.absolute() / f"ckpt_{int(step):010d}",
                    params, force=True,
                    save_args=orbax_utils.save_args_from_target(params))

    train_fn = functools.partial(
        ppo.train,
        num_timesteps=args.num_timesteps,
        num_evals=args.num_evals,
        episode_length=env._config.episode_length,
        num_envs=args.num_envs,
        batch_size=256,
        unroll_length=20,
        num_minibatches=16,          # 🔴 ×num_updates_per_batch ≤ 32
        num_updates_per_batch=2,     #    gfx1100 XLA graph-size ceiling
        # BeyondMimic uses 1e-3, but paired with rsl_rl's adaptive-KL
        # schedule (desired_kl=0.01, which lowers the rate when KL grows).
        # brax PPO has no such schedule, so its ceiling value should not be
        # copied without the mechanism that made it safe.
        learning_rate=args.lr,
        # BeyondMimic uses 0.005, again under rsl_rl's scaling and adaptive-KL
        # schedule. brax does not normalise the entropy term, where 5e-3 lets
        # the entropy bonus outweigh the task reward. 1e-3 is the value that
        # converges on this platform.
        entropy_cost=args.entropy,
        discounting=0.99,            # BeyondMimic: gamma=0.99
        gae_lambda=0.95,             # BeyondMimic: lam=0.95
        clipping_epsilon=0.2,
        normalize_observations=True,
        reward_scaling=1.0,
        action_repeat=1,
        max_grad_norm=1.0,
        seed=args.seed,
        network_factory=network_factory,
        randomization_fn=randomizer,
        progress_fn=progress,
        # Defaults to False, which evaluates the **noisy** policy and hides
        # its real quality: ep_len sat at 24-30 largely because of sampling
        # noise.
        deterministic_eval=True,
        policy_params_fn=policy_params_fn,
        # Playground's State exposes .data rather than brax's .pipeline_state,
        # so its own wrapper is required or AutoResetWrapper raises
        # AttributeError: State object has no attribute pipeline_state
        #
        # full_reset=True is mandatory. At the default of False, auto-reset
        # restores data and obs but **not info**, so info["motion_idx"] keeps
        # advancing: after the first episode the reference index is permanently
        # out of step with the physics and every sample is garbage. The tell
        # was three very different ablations — penalties off, entropy off, both
        # off — producing identical curves, with ep_len dropping from 36 to 22
        # regardless of the reward configuration.
        wrap_env_fn=functools.partial(wrapper.wrap_for_brax_training,
                                      full_reset=True),
    )

    print("Training started (first JIT compile takes 1-2 min)...", flush=True)
    _, params, _ = train_fn(environment=env, eval_env=eval_env)

    ck = ocp.PyTreeCheckpointer()
    ck.save(out.absolute() / "params", params, force=True,
            save_args=orbax_utils.save_args_from_target(params))
    (out / "config.json").write_text(json.dumps({
        "motion": args.motion, "num_envs": args.num_envs,
        "num_timesteps": args.num_timesteps, "domain_rand": args.domain_rand,
        "recipe": "BeyondMimic whole-body tracking (MJX port)",
    }, indent=2))
    print(f"\nDONE  {out}  elapsed {(time.time()-t0)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
