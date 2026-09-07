"""Minimal reproducer for the brax-PPO / ROCm HSA-layer segfault.

Durable replacement for the throwaway /tmp/ppo_min.py used on the cloud
instance (that file is lost on instance restart — this one is version
controlled). See docs/ROCM_BUG_REPORT.md (Root Cause Analysis).

What it does (the smallest thing that still crashes):
  1. Load the Playground Go1 joystick env with the JAX/XLA MJX backend.
  2. Run a handful of brax PPO training steps on the AMD GPU.

Expected on gfx1100 + jax-rocm7 (brax 0.14.2): `Segmentation fault` inside
libhsa-runtime64 during the first PPO training step. env.reset/step/vmap on
their own are fine (see scripts/00_verify_rocm.sh) — only brax's
pmap-over-scan training step triggers it.

Run on the instance:
    cd /workspace/Radeon-hackathon-2026-07/amd-physical-ai-locomotion
    PYTHONPATH="$PWD" python3 scripts/repro_hsa_segfault.py

Capture the stack:
    PYTHONPATH="$PWD" rocgdb -q -batch -ex run -ex bt -ex quit \
        --args python3 scripts/repro_hsa_segfault.py 2>&1 | tail -60

To see the crash turn into a (masked) Python error instead — evidence for
the rocprofiler-interception finding in docs/ROCM_BUG_REPORT.md:
    ROCP_TOOL_LIBRARIES= HSA_TOOLS_LIB= ROCPROFILER_DISABLE=1 \
        PYTHONPATH="$PWD" python3 scripts/repro_hsa_segfault.py
"""
from __future__ import annotations

import functools

from src import config as C

C.set_headless_render_defaults()

import jax  # noqa: E402
from brax.training.agents.ppo import train as ppo  # noqa: E402
from mujoco_playground import registry  # noqa: E402
from mujoco_playground import wrapper as pg_wrapper  # noqa: E402
from mujoco_playground.config import locomotion_params  # noqa: E402

ENV = "Go1JoystickFlatTerrain"


def main() -> None:
    C.assert_gpu(require=True)
    C.apply_jax_compat_shims()
    print(f"[repro] jax devices: {jax.devices()}")

    # Force the classic JAX/XLA MJX backend (Warp backend is unavailable on
    # ROCm — see docs/ROCM_BUG_REPORT.md (Suggested Fix)).
    env_cfg = registry.get_default_config(ENV)
    if "impl" in env_cfg:
        with env_cfg.unlocked():
            env_cfg.impl = "jax"
    env = registry.load(ENV, config=env_cfg)
    print("[repro] env loaded; reset/step/vmap are known-good on their own.")

    # Tiny PPO config: just enough to execute one training step, which is
    # where the HSA-layer segfault happens.
    ppo_params = locomotion_params.brax_ppo_config(ENV)
    ppo_params.num_timesteps = 200_000
    ppo_params.num_evals = 1

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
        randomization_fn=registry.get_domain_randomizer(ENV),
        wrap_env_fn=pg_wrapper.wrap_for_brax_training,
        seed=0,
    )

    print("[repro] starting PPO train — segfault expected in the first step...")
    train_fn(environment=env)
    print("[repro] NO CRASH — the ROCm/brax bug appears resolved on this stack.")


if __name__ == "__main__":
    main()
