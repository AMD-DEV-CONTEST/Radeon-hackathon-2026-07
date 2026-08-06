"""Benchmark SmolVLA inference on CPU vs AMD ROCm GPU.

Measures the VLA policy's single-observation inference cost on each available
device and writes ``benchmark/results.json``:

    latency (ms/inference), throughput (FPS = 1000/latency), GPU memory (MB).

The benchmark loads a real checkpoint through the same ``VLAAgent`` path the demo
uses, then times ``agent.predict`` on a fixed synthetic observation (so the timing
reflects the model, not the sim/renderer). Warmup iterations prime CUDA/HIP kernels
and autotuning before timing.

Usage (on the Radeon machine):
    python benchmark/rocm_perf.py \\
        --checkpoint outputs/train/smolvla_cube_pick/checkpoints/last/pretrained_model \\
        --repo-id so101/cube_pick --dataset-root datasets/cube_pick \\
        --devices cpu cuda --iters 50 --warmup 10

    # smaller model-free sanity check of the harness itself:
    python benchmark/rocm_perf.py --dry-run

Output table:
    Device        Latency      FPS       GPU Mem
    cpu           xxx.x ms     xx.x      -
    cuda          xx.x ms      xxx.x     xxx MB

NOTE: On ROCm, device string ``cuda`` selects the AMD GPU (ROCm torch maps
CUDA APIs onto HIP); ``torch.cuda.max_memory_allocated`` reports HIP allocations.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paths import BENCHMARK_DIR
from simulation import so101


def _fake_observation(img_hw: tuple[int, int] = (240, 320)) -> dict:
    """A fixed synthetic observation matching the agent.predict signature."""
    h, w = img_hw
    rng = np.random.default_rng(0)
    return {
        "image": rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8),
        "wrist_image": rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8),
        "instruction": "Pick the red cube and place it into the basket",
        "state": np.zeros(so101.N_DOF, dtype=np.float32),
    }


def _sync(device: str) -> None:
    import torch

    if device.startswith("cuda") and torch.cuda.is_available():
        torch.cuda.synchronize()


def benchmark_device(
    device: str, checkpoint: str, repo_id: str, dataset_root: str | None,
    *, backend: str, iters: int, warmup: int,
) -> dict:
    """Time agent.predict on one device. Returns a result dict."""
    import torch
    from vla.inference import load_agent

    obs = _fake_observation()

    if device.startswith("cuda") and torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    agent = load_agent(checkpoint, repo_id, dataset_root, backend=backend, device=device)

    # Warmup (kernel compile / autotune / lazy init).
    for _ in range(warmup):
        agent.reset()
        agent.predict(obs["image"], obs["instruction"], obs["state"], wrist_image=obs["wrist_image"])
    _sync(device)

    latencies = []
    for _ in range(iters):
        agent.reset()
        t0 = time.perf_counter()
        agent.predict(obs["image"], obs["instruction"], obs["state"], wrist_image=obs["wrist_image"])
        _sync(device)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    arr = np.asarray(latencies)
    result = {
        "device": device,
        "backend": backend,
        "iters": iters,
        "latency_ms_mean": float(arr.mean()),
        "latency_ms_std": float(arr.std()),
        "latency_ms_p50": float(np.percentile(arr, 50)),
        "latency_ms_p95": float(np.percentile(arr, 95)),
        "fps": float(1000.0 / arr.mean()) if arr.mean() > 0 else None,
        "gpu_mem_mb": None,
    }
    if device.startswith("cuda") and torch.cuda.is_available():
        result["gpu_mem_mb"] = float(torch.cuda.max_memory_allocated() / (1024**2))
        result["gpu_name"] = torch.cuda.get_device_name(0)
        result["torch_hip"] = getattr(torch.version, "hip", None)
    return result


def _print_table(results: list[dict]) -> None:
    print(f"\n{'Device':<10} {'Latency (ms)':>14} {'FPS':>8} {'GPU Mem':>10}")
    print("-" * 46)
    for r in results:
        mem = f"{r['gpu_mem_mb']:.0f} MB" if r.get("gpu_mem_mb") else "-"
        fps = f"{r['fps']:.1f}" if r.get("fps") else "-"
        print(f"{r['device']:<10} {r['latency_ms_mean']:>10.2f}±{r['latency_ms_std']:<3.0f} {fps:>8} {mem:>10}")

    # Speedup line if both cpu and a cuda device were measured.
    by_dev = {r["device"]: r for r in results}
    if "cpu" in by_dev and any(d.startswith("cuda") for d in by_dev):
        gpu = next(by_dev[d] for d in by_dev if d.startswith("cuda"))
        speedup = by_dev["cpu"]["latency_ms_mean"] / gpu["latency_ms_mean"]
        print(f"\nAMD GPU speedup over CPU: {speedup:.1f}x")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark SmolVLA inference: CPU vs AMD ROCm GPU.")
    parser.add_argument("--checkpoint", help="Trained policy checkpoint dir.")
    parser.add_argument("--repo-id", help="Dataset repo id the policy trained on.")
    parser.add_argument("--dataset-root", default=None)
    parser.add_argument("--backend", default="smolvla")
    parser.add_argument("--devices", nargs="+", default=["cpu", "cuda"],
                        help="Devices to benchmark (default: cpu cuda).")
    parser.add_argument("--iters", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--out", default=None, help="Results JSON (default: benchmark/results.json).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Emit placeholder results without loading a model (harness sanity check).")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else BENCHMARK_DIR / "results.json"

    if args.dry_run:
        results = [
            {"device": "cpu", "backend": args.backend, "latency_ms_mean": 0.0,
             "latency_ms_std": 0.0, "fps": None, "gpu_mem_mb": None, "note": "dry-run placeholder"},
        ]
    else:
        if not (args.checkpoint and args.repo_id):
            raise SystemExit("Provide --checkpoint and --repo-id (or use --dry-run).")
        import torch

        results = []
        for device in args.devices:
            if device.startswith("cuda") and not torch.cuda.is_available():
                print(f"[bench] skipping {device}: torch.cuda not available (no ROCm GPU visible).")
                continue
            print(f"[bench] benchmarking {device} ...")
            results.append(benchmark_device(
                device, args.checkpoint, args.repo_id, args.dataset_root,
                backend=args.backend, iters=args.iters, warmup=args.warmup,
            ))

    _print_table(results)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"results": results, "meta": {"backend": args.backend, "iters": args.iters}}
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n[bench] results -> {out_path}")


if __name__ == "__main__":
    main()
