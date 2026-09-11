from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from parcel_sorter.genesis_env import initialize_genesis
from parcel_sorter.provenance import runtime_report


def rocm_snapshot() -> dict[str, Any] | None:
    try:
        completed = subprocess.run(
            ["rocm-smi", "--showuse", "--showmemuse", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return json.loads(completed.stdout)
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def run_case(backend: str, num_envs: int, warmup_steps: int, measured_steps: int) -> dict[str, Any]:
    gs, torch, np = initialize_genesis(backend)
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1.0 / 240),
        rigid_options=gs.options.RigidOptions(
            box_box_detection=True,
            enable_collision=True,
            enable_joint_limit=True,
        ),
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
        show_viewer=False,
    )
    scene.add_entity(gs.morphs.Plane())
    robot = scene.add_entity(gs.morphs.MJCF(file="xml/franka_emika_panda/panda.xml"))
    parcel = scene.add_entity(gs.morphs.Box(size=(0.06, 0.045, 0.04), pos=(0.58, 0.0, 0.02)))
    scene.build(n_envs=num_envs, env_spacing=(1.25, 1.25))

    qpos = np.asarray((-1.0124, 1.5559, 1.3662, -1.6878, -1.5799, 1.7757, 1.4602, 0.04, 0.04))
    robot.set_qpos(np.tile(qpos, (num_envs, 1)))
    x = np.linspace(0.48, 0.68, num_envs)
    y = np.linspace(-0.15, 0.15, num_envs)
    parcel.set_pos(np.stack((x, y, np.full(num_envs, 0.02)), axis=-1), zero_velocity=True)
    robot.control_dofs_position(np.tile(qpos[:, None].T, (num_envs, 1)))

    for _ in range(warmup_steps):
        scene.step()
    if backend != "cpu":
        torch.cuda.synchronize()
    before = rocm_snapshot() if backend == "rocm" else None
    started = time.perf_counter()
    for _ in range(measured_steps):
        scene.step()
    if backend != "cpu":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    after = rocm_snapshot() if backend == "rocm" else None
    scene.destroy()

    return {
        "num_envs": num_envs,
        "measured_steps": measured_steps,
        "elapsed_seconds": elapsed,
        "physics_steps_per_second": measured_steps / elapsed,
        "environment_steps_per_second": measured_steps * num_envs / elapsed,
        "rocm_before": before,
        "rocm_after": after,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep Genesis parallel environment throughput")
    parser.add_argument("--backend", choices=("rocm", "cuda", "cpu"), default="rocm")
    parser.add_argument("--env-counts", default="1,16,64,128")
    parser.add_argument("--warmup-steps", type=int, default=30)
    parser.add_argument("--steps", type=int, default=240)
    parser.add_argument("--output", default="outputs/benchmarks/parallel.json")
    args = parser.parse_args()
    try:
        env_counts = tuple(int(value) for value in args.env_counts.split(","))
    except ValueError as exc:
        parser.error(f"invalid env-counts: {exc}")
    if not env_counts or any(value < 1 for value in env_counts):
        parser.error("env-counts must contain positive integers")
    if args.warmup_steps < 0 or args.steps < 1:
        parser.error("warmup-steps cannot be negative and steps must be positive")

    cases = [run_case(args.backend, count, args.warmup_steps, args.steps) for count in env_counts]
    payload = {"runtime": runtime_report(), "backend": args.backend, "cases": cases}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
