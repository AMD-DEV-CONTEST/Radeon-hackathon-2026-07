#!/usr/bin/env python3
"""T3-P0 probe 1: motrix backend throughput + frozen-stack behavior sanity.

Preregistered gates (2026-08-01 00:30 UTC): BBC-in-the-loop throughput at
num_envs in {64, 256, 1024} (lever holds at >=5e4 steps/s, fails <1e4);
straight-walk sanity (>=1.5 m in 500 steps, no fall, within 30% of the
same-config MuJoCo run); stairs box fragment composes.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from cpp_loco_sanity import _sha256  # noqa: E402
from run_bbc_sanity import _device, _write_json  # noqa: E402
from run_source_task import HIGH_CHECKPOINT  # noqa: E402
from t2_env import VectorAgilityStack  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "assets"
RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-T3-P0"
FLAT_SPEC = SimpleNamespace(
    name="flat", goals=((-3.0, 0.0, 0.3), (3.0, 0.0, 0.3)), obstacle_index=1
)


class _FlatSampler:
    @staticmethod
    def sample_height(xy: np.ndarray) -> np.ndarray:
        return np.zeros(np.asarray(xy).shape[:-1], dtype=np.float64)


def build_stack(backend: str, num_envs: int, device, seed: int, fragment=None):
    return VectorAgilityStack(
        "flat",
        num_envs,
        device,
        seed,
        spec=FLAT_SPEC,
        sampler=_FlatSampler(),
        fragment_file=fragment,
        backend=backend,
    )


def frozen_rollout(stack, steps: int) -> dict[str, Any]:
    actor = stack.adapter.high_model
    started = time.monotonic()
    for _ in range(steps):
        obs = stack.observe()
        with torch.no_grad():
            emb = actor(
                stack.high_input(obs), hist_encoding=True, scandots_latent=None
            )
            stack.step_with_action(
                obs, torch.argmax(actor.actor_d(emb), -1), actor.actor_c(emb)
            )
    elapsed = time.monotonic() - started
    base = stack.backend.get_base_pos().copy()
    return {
        "steps_per_sec": stack.num_envs * steps / elapsed,
        "final_base": base[0].tolist(),
        "forward_m": float(base[0, 0] - stack.goals[0][0]),
        "mean_z": float(base[:, 2].mean()),
    }


def probe(args) -> dict[str, Any]:
    device = _device(args.device)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    checks: dict[str, Any] = {}
    metrics: dict[str, Any] = {}

    # (b) behaviour sanity: single-env straight walk on both backends
    walks = {}
    for backend in ("mujoco", "motrix"):
        try:
            stack = build_stack(backend, 1, device, args.seed)
            walks[backend] = frozen_rollout(stack, 500)
            stack.env.close()
        except Exception as exc:
            walks[backend] = {"error": f"{type(exc).__name__}: {exc}",
                              "trace": traceback.format_exc()[-800:]}
    metrics["straight_walk"] = walks
    ok = "error" not in walks.get("motrix", {})
    checks["motrix_composes_and_steps"] = ok
    if ok and "error" not in walks["mujoco"]:
        fm, fx = walks["mujoco"]["forward_m"], walks["motrix"]["forward_m"]
        checks["motrix_walks_forward"] = fx >= 1.5 and walks["motrix"]["mean_z"] > 0.22
        checks["cross_backend_within_30pct"] = (
            abs(fx - fm) <= 0.3 * max(abs(fm), 1e-6)
        )

    # (a) throughput sweep, BBC in the loop
    sweep = {}
    if ok:
        for n in args.env_sweep:
            try:
                stack = build_stack("motrix", n, device, args.seed)
                frozen_rollout(stack, 10)  # warmup
                sweep[n] = frozen_rollout(stack, args.throughput_steps)[
                    "steps_per_sec"
                ]
                stack.env.close()
            except Exception as exc:
                sweep[n] = f"{type(exc).__name__}: {exc}"
    metrics["motrix_steps_per_sec"] = sweep
    numeric = [v for v in sweep.values() if isinstance(v, float)]
    peak = max(numeric) if numeric else 0.0
    metrics["peak_steps_per_sec"] = peak
    checks["lever_holds_5e4"] = peak >= 5e4
    checks["lever_fails_1e4"] = peak < 1e4  # informational kill line

    # (c) stairs box fragment composes on motrix
    try:
        stack = build_stack(
            "motrix", 4, device, args.seed, fragment=ASSETS / "stairs_r010.xml"
        )
        frozen_rollout(stack, 20)
        stack.env.close()
        checks["stairs_fragment_composes"] = True
    except Exception as exc:
        checks["stairs_fragment_composes"] = False
        metrics["stairs_fragment_error"] = f"{type(exc).__name__}: {exc}"

    hard = ["motrix_composes_and_steps"]
    status = "PASSED" if all(checks.get(k) for k in hard) else "FAILED"
    return {
        "run_id": "NAG-T3-P0-MOTRIX",
        "status": status,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": "T3-P0 probe 1: motrix throughput + frozen-stack sanity",
        "seed": args.seed,
        "checks": checks,
        "metrics": metrics,
        "contracts": {
            "env_sweep": list(args.env_sweep),
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "runner_sha256": _sha256(Path(__file__)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--env-sweep", type=int, nargs="+", default=[64, 256, 1024])
    parser.add_argument("--throughput-steps", type=int, default=100)
    args = parser.parse_args()
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    try:
        payload = probe(args)
    except Exception as exc:
        payload = {
            "run_id": "NAG-T3-P0-MOTRIX",
            "status": "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc()[-1500:],
        }
    path = RESULTS_ROOT / f"result_{stamp}.json"
    _write_json(path, payload)
    shutil.copy2(path, RESULTS_ROOT / "result.json")
    print(f"{payload['status']}: {path}")
    if "checks" in payload:
        print("checks:", payload["checks"])
        print("throughput:", payload["metrics"].get("motrix_steps_per_sec"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
