"""Benchmark parallel recording at different n_envs values.

Measures: episode/s, effective FPS, GPU utilization, VRAM for each n_envs.
Two modes: (1) pure sim (no render) to measure physics throughput,
(2) with rendering to measure recording throughput.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from build_scene import build_scene
from scene_config import FRANKA_QPOS
from genesis.utils.geom import trans_R_to_T, euler_to_R


def get_gpu_stats():
    """Get GPU utilization and VRAM via rocm-smi."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showuse", "--showmeminfo", "vram"],
            capture_output=True, text=True, timeout=5
        )
        gpu_util = "?"
        vram_used = 0
        for line in result.stdout.split("\n"):
            if "GPU use (%):" in line:
                gpu_util = line.split("GPU use (%):")[1].strip()
            if "VRAM Total Used Memory (B):" in line:
                vram_str = line.split("VRAM Total Used Memory (B):")[1].strip()
                vram_used = int(vram_str) / 1e9
        return gpu_util, vram_used
    except Exception:
        return "?", 0


def benchmark_n_envs(n_envs: int, steps: int = 300, with_render: bool = True) -> dict:
    """Run n_envs parallel sim for `steps` steps, measure throughput + VRAM."""
    gs.init(backend=gs.gpu)
    bundle = build_scene(
        n_envs=n_envs,
        add_world_cam=True,
        add_wrist_cam=True,
        colors=("red", "blue", "green"),
    )

    # Attach wrist cam
    if bundle.wrist_cam is not None and bundle._wrist_link is not None:
        offset_T = trans_R_to_T(
            np.asarray([0.04, 0.0, 0.0], dtype=np.float64),
            euler_to_R(np.array([180.0, 0.0, 0.0], dtype=np.float64)),
        )
        bundle.wrist_cam.attach(bundle._wrist_link, offset_T)
        bundle.wrist_cam.move_to_attach()

    n = n_envs
    qpos = np.tile(np.array(FRANKA_QPOS), (n, 1))

    # Warmup
    for _ in range(20):
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()

    torch.cuda.synchronize()

    # Sample GPU util during run (background)
    import threading
    gpu_samples = []

    def sample_gpu():
        for _ in range(10):
            util, vram = get_gpu_stats()
            if util != "?":
                gpu_samples.append(int(str(util).strip("%")))
            time.sleep(0.2)

    t_gpu = threading.Thread(target=sample_gpu)
    t_gpu.start()

    # Measure VRAM before run
    free_before, total = torch.cuda.mem_get_info(0)
    vram_torch = (total - free_before) / 1e9

    # Run benchmark
    render_every = 3  # ~33fps from 100Hz
    frames_captured = 0
    t0 = time.time()
    for step in range(steps):
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if with_render and step % render_every == 0:
            for ei in range(n):
                bundle.world_cam._env_idx = ei
                bundle.world_cam.render(rgb=True)
                bundle.wrist_cam._env_idx = ei
                bundle.wrist_cam.render(rgb=True)
                frames_captured += 1
    torch.cuda.synchronize()
    t1 = time.time()

    t_gpu.join(timeout=2)

    elapsed = t1 - t0
    sim_fps = steps / elapsed
    eps_per_sec = n * sim_fps / 400  # ~400 steps per episode
    effective_fps = frames_captured / elapsed if frames_captured > 0 else 0
    gpu_util = f"{np.mean(gpu_samples):.0f}%" if gpu_samples else "?"
    vram_gb = vram_torch

    result = {
        "n_envs": n_envs,
        "sim_fps": sim_fps,
        "eps_per_sec": eps_per_sec,
        "effective_fps": effective_fps,
        "gpu_util": gpu_util,
        "vram_gb": vram_gb,
        "elapsed": elapsed,
        "with_render": with_render,
    }

    del bundle
    gs.destroy()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--envs", type=int, nargs="+", default=[8, 16, 32, 64, 96, 128])
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--no-render", action="store_true", help="Skip rendering (pure sim throughput)")
    args = parser.parse_args()

    mode = "pure sim" if args.no_render else "with render"
    print(f"\n=== Benchmark: {mode} ===\n")
    print(f"{'n_envs':>6} | {'Episode/s':>10} | {'FPS':>8} | {'GPU%':>6} | {'VRAM':>8} | {'sim_fps':>8}")
    print("-" * 70)

    results = []
    for n in args.envs:
        try:
            r = benchmark_n_envs(n, args.steps, with_render=not args.no_render)
            results.append(r)
            print(f"{r['n_envs']:>6} | {r['eps_per_sec']:>10.1f} | {r['effective_fps']:>8.0f} | {r['gpu_util']:>6} | {r['vram_gb']:>6.1f} GB | {r['sim_fps']:>8.0f}")
        except Exception as e:
            print(f"{n:>6} | ERROR: {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()

    print()
    print(f"=== Summary ({mode}) ===")
    print(f"{'n_envs':>6} | {'Episode/s':>10} | {'FPS':>8} | {'GPU%':>6} | {'VRAM':>8}")
    print("-" * 55)
    for r in results:
        print(f"{r['n_envs']:>6} | {r['eps_per_sec']:>10.1f} | {r['effective_fps']:>8.0f} | {r['gpu_util']:>6} | {r['vram_gb']:>6.1f} GB")


if __name__ == "__main__":
    main()