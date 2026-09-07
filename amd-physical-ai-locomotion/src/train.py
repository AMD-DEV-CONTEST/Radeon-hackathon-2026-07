"""Train a locomotion policy with Brax PPO on top of MuJoCo Playground (MJX).

Runs on the AMD GPU via the ROCm build of JAX. Asserts GPU usage up front so
that "training executed on AMD Radeon" is provable (not silently on CPU).

Example:
    python -m src.train --env Go1JoystickFlatTerrain --seed 0
    # quick smoke test (few steps, just to confirm the pipeline runs):
    python -m src.train --num-timesteps 200000
"""
from __future__ import annotations

import argparse
import functools
import json
import time

# Must set render/XLA defaults before importing jax.
from src import config as C

C.set_headless_render_defaults()

import jax  # noqa: E402
from brax.training.agents.ppo import train as ppo  # noqa: E402
from mujoco_playground import registry  # noqa: E402
from mujoco_playground import wrapper as pg_wrapper  # noqa: E402
from mujoco_playground.config import locomotion_params  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Locomotion PPO training on AMD/ROCm.")
    p.add_argument("--env", default=C.DEFAULT_ENV, help="Playground env name.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--num-timesteps",
        type=int,
        default=None,
        help="Override total env steps (use a small value like 200000 for a smoke test).",
    )
    p.add_argument(
        "--allow-cpu",
        action="store_true",
        help="Do not hard-fail if JAX is on CPU (for local dry runs only).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    C.ensure_dirs()
    C.assert_gpu(require=not args.allow_cpu)
    C.apply_jax_compat_shims()

    env_name = args.env
    print(f"[train] env={env_name} seed={args.seed}")

    # Environment + tuned PPO config straight from Playground.
    # Force the classic JAX/XLA MJX backend (impl="jax"). mujoco-mjx >=3.10
    # defaults to the Warp backend, which is not available on the ROCm JAX
    # build here (mjx.put_model then raises "type object 'int' has no
    # attribute 'WARP'"). The JAX backend is the one verified in
    # scripts/00_verify_rocm.sh and runs on the AMD GPU via ROCm.
    env_cfg = registry.get_default_config(env_name)
    if "impl" in env_cfg:
        with env_cfg.unlocked():
            env_cfg.impl = "jax"
    env = registry.load(env_name, config=env_cfg)
    ppo_params = locomotion_params.brax_ppo_config(env_name)
    if args.num_timesteps is not None:
        ppo_params.num_timesteps = args.num_timesteps
        # Keep at least one eval for a quick run.
        ppo_params.num_evals = max(1, min(ppo_params.num_evals, 2))

    # Domain randomization (if the env provides one) improves robustness /
    # generalization — one of the track's judged capabilities.
    randomizer = registry.get_domain_randomizer(env_name)

    # Progress logging -> a metrics file for the technical report.
    metrics_log: list[dict] = []
    t0 = time.time()

    def progress(num_steps: int, metrics: dict) -> None:
        row = {"steps": int(num_steps), "wall_s": round(time.time() - t0, 1)}
        for k, v in metrics.items():
            try:
                row[k] = float(v)
            except (TypeError, ValueError):
                pass
        metrics_log.append(row)
        reward = row.get("eval/episode_reward", float("nan"))
        print(f"[train] steps={num_steps:>12,}  reward={reward:8.3f}  t={row['wall_s']}s")

    # Build the PPO train fn. brax's ppo.train takes the config fields as kwargs.
    ppo_kwargs = dict(ppo_params)
    network_factory = None
    if "network_factory" in ppo_kwargs:
        from brax.training.agents.ppo import networks as ppo_networks

        nf = ppo_kwargs.pop("network_factory")
        network_factory = functools.partial(
            ppo_networks.make_ppo_networks, **dict(nf)
        )

    train_fn = functools.partial(
        ppo.train,
        **ppo_kwargs,
        network_factory=network_factory,
        randomization_fn=randomizer,
        wrap_env_fn=pg_wrapper.wrap_for_brax_training,
        progress_fn=progress,
        seed=args.seed,
    )

    print("[train] compiling & training (first step includes JIT compile)...")
    make_inference_fn, params, _ = train_fn(environment=env)

    # Persist params + metrics for eval/render and the report.
    ckpt_path = C.CKPT_DIR / f"{env_name}_seed{args.seed}.pkl"
    _save_params(ckpt_path, params)
    (C.LOG_DIR / f"{env_name}_seed{args.seed}_metrics.json").write_text(
        json.dumps(metrics_log, indent=2)
    )
    print(f"[train] done in {time.time() - t0:.1f}s")
    print(f"[train] checkpoint -> {ckpt_path}")
    print(f"[train] metrics    -> {C.LOG_DIR}")


def _save_params(path, params) -> None:
    import pickle

    with open(path, "wb") as f:
        pickle.dump(params, f)


if __name__ == "__main__":
    main()
