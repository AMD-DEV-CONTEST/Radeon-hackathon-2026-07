"""Throughput and latency micro-benchmarks for simulation and optional policy."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch

from radeonvla.paths import BENCHMARK_DIR, PROJECT_ROOT
from radeonvla.scene import AppearanceDR, build_scene, init_genesis
from radeonvla.scene_config import FRANKA_QPOS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "eval.yaml")
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--backend", choices=("cpu", "gpu", "amdgpu"), default=None)
    parser.add_argument("--policy-path", default=None, help="Optional checkpoint for inference latency.")
    parser.add_argument("--repo-id", default="visiobot/radeonvla_reflex")
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backend = args.backend or ("cpu" if args.cpu else "gpu")
    init_genesis(backend=backend, seed=0)
    bundle = build_scene(
        show_viewer=False,
        add_world_cam=True,
        add_wrist_cam=True,
        appearance=AppearanceDR(seed=0),
    )
    hold = np.array(FRANKA_QPOS)

    for _ in range(args.warmup):
        bundle.franka.control_dofs_position(hold)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if bundle.world_cam is not None:
            bundle.world_cam.render(rgb=True)

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    for _ in range(args.steps):
        bundle.franka.control_dofs_position(hold)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if bundle.world_cam is not None:
            bundle.world_cam.render(rgb=True)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - t0
    sim_sps = args.steps / max(elapsed, 1e-9)

    result = {
        "backend": backend,
        "torch": torch.__version__,
        "torch_hip": torch.version.hip,
        "sim_steps": args.steps,
        "sim_elapsed_s": elapsed,
        "simulation_steps_per_second": sim_sps,
        "peak_vram_mib": (
            torch.cuda.max_memory_allocated() / 1024**2 if torch.cuda.is_available() else None
        ),
    }

    if args.policy_path:
        from radeonvla.artifact_io import sha256_path
        from radeonvla.evaluate import build_observation, load_policy

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        device = "cpu" if args.cpu else args.device
        pb = load_policy(args.policy_path, args.repo_id, args.dataset_root, device)
        pb.reset()
        # Warmup
        for _ in range(10):
            obs = build_observation(bundle, pb)
            _ = pb.select_action(obs, "Pick the banana and place it in the left bowl.")
        lat = []
        for _ in range(50):
            obs = build_observation(bundle, pb)
            t1 = time.perf_counter()
            _ = pb.select_action(obs, "Pick the banana and place it in the left bowl.")
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            lat.append((time.perf_counter() - t1) * 1000.0)
        result["inference_latency_ms"] = {
            "mean": float(np.mean(lat)),
            "p50": float(np.percentile(lat, 50)),
            "p95": float(np.percentile(lat, 95)),
        }
        result["inference_peak_vram_mib"] = (
            torch.cuda.max_memory_allocated() / 1024**2 if torch.cuda.is_available() else None
        )
        result["checkpoint_sha256"] = sha256_path(args.policy_path)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.output or (BENCHMARK_DIR / f"benchmark_{stamp}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"[benchmark] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
