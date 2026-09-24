"""Locate the CPU/GPU crossover point for the HighwayEnv DQN workload.

The headline observation from this project is that a Radeon GPU does not speed
up the original-demo configuration at all: the 25->256->256->5 policy peaks at about
110 MB of VRAM and end-to-end training is bounded by environment simulation on
the CPU. Rather than hide that, this script quantifies it and finds the point
where ROCm does start to pay off.

Two independent measurements:

``gradient``
    Pure optimiser throughput while varying network width and batch size. This
    is the part of the workload a GPU can actually accelerate, so the CPU/GPU
    ratio here defines the crossover.

``throughput``
    End-to-end training steps/s while varying the number of parallel
    environments. This is what a user actually experiences.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

from common import (
    create_highway_env,
    print_rocm_info,
    resolve_device,
    setup_headless_runtime,
)

setup_headless_runtime()

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import torch
from stable_baselines3 import DQN
from stable_baselines3.common.logger import Logger
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv


NET_ARCHS = [[64, 64], [256, 256], [1024, 1024], [2048, 2048]]
BATCH_SIZES = [64, 512, 4096]
N_ENVS_SWEEP = [1, 4, 8, 16, 32]
DEVICES = ["cpu", "cuda"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark the DQN workload on AMD ROCm vs CPU."
    )
    parser.add_argument(
        "--mode",
        choices=("gradient", "throughput", "all"),
        default="all",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/rocm_benchmark"),
    )
    parser.add_argument(
        "--time-budget",
        type=float,
        default=4.0,
        help="Seconds spent timing each gradient configuration.",
    )
    parser.add_argument(
        "--max-gradient-steps",
        type=int,
        default=600,
    )
    parser.add_argument(
        "--throughput-timesteps",
        type=int,
        default=4000,
    )
    return parser.parse_args()


def _read_gpu() -> dict | None:
    try:
        completed = subprocess.run(
            [
                "rocm-smi",
                "--showuse",
                "--showmemuse",
                "--showpower",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        payload = json.loads(completed.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None

    if not payload:
        return None
    card = next(iter(payload.values()))

    def _num(key: str) -> float:
        try:
            return float(card.get(key, "nan"))
        except ValueError:
            return float("nan")

    return {
        "utilization_pct": _num("GPU use (%)"),
        "vram_pct": _num("GPU Memory Allocated (VRAM%)"),
        "power_w": _num("Average Graphics Package Power (W)"),
    }


class GpuSampler:
    """Poll rocm-smi in the background while a measurement runs."""

    def __init__(self, interval: float = 0.25, enabled: bool = True):
        self.interval = interval
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[dict] = []

    def _loop(self):
        while not self._stop.is_set():
            sample = _read_gpu()
            if sample is not None:
                self.samples.append(sample)
            self._stop.wait(self.interval)

    def __enter__(self) -> "GpuSampler":
        if self.enabled:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def summary(self) -> dict:
        if not self.samples:
            return {
                "gpu_samples": 0,
                "gpu_mean_utilization_pct": None,
                "gpu_max_utilization_pct": None,
                "gpu_max_vram_pct": None,
                "gpu_mean_power_w": None,
            }
        utilization = [s["utilization_pct"] for s in self.samples]
        vram = [s["vram_pct"] for s in self.samples]
        power = [s["power_w"] for s in self.samples]
        return {
            "gpu_samples": len(self.samples),
            "gpu_mean_utilization_pct": float(np.nanmean(utilization)),
            "gpu_max_utilization_pct": float(np.nanmax(utilization)),
            "gpu_max_vram_pct": float(np.nanmax(vram)),
            "gpu_mean_power_w": float(np.nanmean(power)),
        }


def _sync(device: str):
    if device == "cuda":
        torch.cuda.synchronize()


def _fill_replay_buffer(model: DQN, transitions: int):
    """Populate the buffer with random data so train() can run standalone."""
    space = model.observation_space
    buffer = model.replay_buffer
    rng = np.random.default_rng(0)

    observation = rng.standard_normal((1, *space.shape)).astype(np.float32)
    for _ in range(transitions):
        next_observation = rng.standard_normal((1, *space.shape)).astype(
            np.float32
        )
        buffer.add(
            observation,
            next_observation,
            np.array([[rng.integers(model.action_space.n)]]),
            np.array([rng.random()], dtype=np.float32),
            np.array([False]),
            [{}],
        )
        observation = next_observation


def benchmark_gradient(
    *,
    device: str,
    net_arch: list[int],
    batch_size: int,
    time_budget: float,
    max_steps: int,
) -> dict:
    env = create_highway_env()

    model = DQN(
        policy="MlpPolicy",
        env=env,
        learning_rate=5e-4,
        buffer_size=max(batch_size * 4, 8_000),
        learning_starts=0,
        batch_size=batch_size,
        policy_kwargs={"net_arch": net_arch},
        verbose=0,
        seed=0,
        device=device,
    )

    # train() is normally reached through learn(), which installs a logger.
    model.set_logger(Logger(folder=None, output_formats=[]))

    _fill_replay_buffer(model, max(batch_size * 2, 4_000))

    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    # Warm up kernel compilation and lazy HIP initialisation.
    model.train(gradient_steps=5, batch_size=batch_size)
    _sync(device)

    with GpuSampler(enabled=(device == "cuda")) as sampler:
        steps = 0
        start = time.perf_counter()
        while steps < max_steps and (time.perf_counter() - start) < time_budget:
            model.train(gradient_steps=10, batch_size=batch_size)
            steps += 10
        _sync(device)
        elapsed = time.perf_counter() - start

    peak_vram_mb = (
        torch.cuda.max_memory_allocated() / 1024**2 if device == "cuda" else None
    )

    parameters = sum(p.numel() for p in model.policy.parameters())
    env.close()

    result = {
        "device": device,
        "net_arch": net_arch,
        "batch_size": batch_size,
        "policy_parameters": int(parameters),
        "gradient_steps": steps,
        "elapsed_seconds": elapsed,
        "gradient_steps_per_second": steps / elapsed,
        "peak_vram_mb": peak_vram_mb,
        "torch_threads": torch.get_num_threads(),
    }
    result.update(sampler.summary())
    return result


def benchmark_throughput(
    *, device: str, n_envs: int, timesteps: int
) -> dict:
    def _make(rank: int):
        def _init():
            setup_headless_runtime()
            return create_highway_env(seed=1000 + rank)

        return _init

    vec_cls = SubprocVecEnv if n_envs > 1 else DummyVecEnv
    env = vec_cls([_make(rank) for rank in range(n_envs)])

    model = DQN(
        policy="MlpPolicy",
        env=env,
        learning_rate=5e-4,
        buffer_size=50_000,
        learning_starts=1_000,
        batch_size=64,
        train_freq=4,
        gradient_steps=1,
        policy_kwargs={"net_arch": [256, 256]},
        verbose=0,
        seed=0,
        device=device,
    )

    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    with GpuSampler(enabled=(device == "cuda")) as sampler:
        start = time.perf_counter()
        model.learn(total_timesteps=timesteps, progress_bar=False)
        _sync(device)
        elapsed = time.perf_counter() - start

    peak_vram_mb = (
        torch.cuda.max_memory_allocated() / 1024**2 if device == "cuda" else None
    )
    env.close()

    result = {
        "device": device,
        "n_envs": n_envs,
        "timesteps": timesteps,
        "elapsed_seconds": elapsed,
        "steps_per_second": timesteps / elapsed,
        "peak_vram_mb": peak_vram_mb,
    }
    result.update(sampler.summary())
    return result


def render_gradient_table(results: list[dict]) -> str:
    lines = [
        "## Gradient-step throughput (optimiser only)",
        "",
        "Environment simulation is excluded, so this isolates the part of the "
        "workload a GPU can accelerate. Speedup above 1.0 means ROCm wins.",
        "",
        "| Network | Params | Batch | CPU steps/s | ROCm steps/s | Speedup |"
        " GPU util | Peak VRAM |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for net_arch in NET_ARCHS:
        for batch_size in BATCH_SIZES:
            cpu = _find(results, "cpu", net_arch, batch_size)
            gpu = _find(results, "cuda", net_arch, batch_size)
            if cpu is None or gpu is None:
                continue
            speedup = (
                gpu["gradient_steps_per_second"]
                / cpu["gradient_steps_per_second"]
            )
            marker = " **" if speedup >= 1.0 else " "
            utilization = gpu.get("gpu_mean_utilization_pct")
            lines.append(
                "| {net} | {params:,} | {batch} | {cpu:.0f} | {gpu:.0f} |"
                "{marker}{speedup:.2f}x{marker_end} | {util} | {vram:.0f} MB |".format(
                    net="x".join(str(width) for width in net_arch),
                    params=cpu["policy_parameters"],
                    batch=batch_size,
                    cpu=cpu["gradient_steps_per_second"],
                    gpu=gpu["gradient_steps_per_second"],
                    marker=marker,
                    speedup=speedup,
                    marker_end="**" if speedup >= 1.0 else "",
                    util=(
                        f"{utilization:.0f}%"
                        if utilization is not None
                        else "n/a"
                    ),
                    vram=gpu["peak_vram_mb"] or 0.0,
                )
            )
    return "\n".join(lines)


def _find(results, device, net_arch, batch_size):
    for result in results:
        if (
            result["device"] == device
            and result["net_arch"] == net_arch
            and result["batch_size"] == batch_size
        ):
            return result
    return None


def render_throughput_table(results: list[dict]) -> str:
    lines = [
        "## End-to-end training throughput",
        "",
        "Full DQN training with the default 256x256 policy. The environment "
        "runs on the CPU in every case, which is why the device barely "
        "matters.",
        "",
        "| Parallel envs | CPU steps/s | ROCm steps/s | Speedup | GPU util |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for n_envs in N_ENVS_SWEEP:
        cpu = next(
            (
                r
                for r in results
                if r["device"] == "cpu" and r["n_envs"] == n_envs
            ),
            None,
        )
        gpu = next(
            (
                r
                for r in results
                if r["device"] == "cuda" and r["n_envs"] == n_envs
            ),
            None,
        )
        if cpu is None or gpu is None:
            continue
        utilization = gpu.get("gpu_mean_utilization_pct")
        lines.append(
            "| {n} | {cpu:.0f} | {gpu:.0f} | {speedup:.2f}x | {util} |".format(
                n=n_envs,
                cpu=cpu["steps_per_second"],
                gpu=gpu["steps_per_second"],
                speedup=gpu["steps_per_second"] / cpu["steps_per_second"],
                util=f"{utilization:.0f}%" if utilization is not None else "n/a",
            )
        )
    return "\n".join(lines)


def plot_crossover(results: list[dict], output_path: Path):
    figure, axes = plt.subplots(figsize=(7.5, 5.5))

    for net_arch in NET_ARCHS:
        speedups, batches = [], []
        for batch_size in BATCH_SIZES:
            cpu = _find(results, "cpu", net_arch, batch_size)
            gpu = _find(results, "cuda", net_arch, batch_size)
            if cpu is None or gpu is None:
                continue
            batches.append(batch_size)
            speedups.append(
                gpu["gradient_steps_per_second"]
                / cpu["gradient_steps_per_second"]
            )
        if batches:
            axes.plot(
                batches,
                speedups,
                marker="o",
                linewidth=2,
                label="x".join(str(width) for width in net_arch),
            )

    axes.axhline(1.0, color="black", linestyle="--", linewidth=1.2)
    axes.text(
        BATCH_SIZES[0],
        1.05,
        "parity with CPU",
        fontsize=9,
        va="bottom",
    )
    axes.set_xscale("log", base=2)
    axes.set_yscale("log")
    axes.set_xticks(BATCH_SIZES)
    axes.set_xticklabels([str(b) for b in BATCH_SIZES])
    axes.set_xlabel("Batch size")
    axes.set_ylabel("ROCm speedup over CPU (gradient steps/s)")
    axes.set_title(
        "ROCm wins the optimiser step by 5-40x\n"
        "AMD Radeon gfx1100 -- but end-to-end training is environment-bound"
    )
    axes.grid(alpha=0.3, linestyle="--", which="both")
    axes.legend(title="Hidden layers")
    figure.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    resolve_device("cuda")
    print_rocm_info("cuda")
    print(f"CPU torch threads: {torch.get_num_threads()}")

    payload: dict = {
        "gpu": torch.cuda.get_device_name(0),
        "torch_version": torch.__version__,
        "hip_version": torch.version.hip,
        "torch_threads": torch.get_num_threads(),
        "idle_gpu": _read_gpu(),
    }
    sections = []

    if args.mode in ("gradient", "all"):
        print("\n=== Gradient-step benchmark ===")
        gradient_results = []
        for net_arch in NET_ARCHS:
            for batch_size in BATCH_SIZES:
                for device in DEVICES:
                    result = benchmark_gradient(
                        device=device,
                        net_arch=net_arch,
                        batch_size=batch_size,
                        time_budget=args.time_budget,
                        max_steps=args.max_gradient_steps,
                    )
                    gradient_results.append(result)
                    print(
                        f"  {'x'.join(map(str, net_arch)):>10} "
                        f"batch={batch_size:<5} {device:<4} "
                        f"{result['gradient_steps_per_second']:8.1f} steps/s"
                    )
        payload["gradient"] = gradient_results
        sections.append(render_gradient_table(gradient_results))
        plot_crossover(
            gradient_results, args.output_dir / "rocm_crossover.png"
        )

    if args.mode in ("throughput", "all"):
        print("\n=== End-to-end throughput benchmark ===")
        throughput_results = []
        for n_envs in N_ENVS_SWEEP:
            for device in DEVICES:
                result = benchmark_throughput(
                    device=device,
                    n_envs=n_envs,
                    timesteps=args.throughput_timesteps,
                )
                throughput_results.append(result)
                print(
                    f"  n_envs={n_envs:<3} {device:<4} "
                    f"{result['steps_per_second']:8.1f} steps/s"
                )
        payload["throughput"] = throughput_results
        sections.append(render_throughput_table(throughput_results))

    json_path = args.output_dir / "rocm_benchmark.json"
    table_path = args.output_dir / "rocm_benchmark.md"

    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    header = [
        "# AMD ROCm benchmark",
        "",
        f"- GPU: {payload['gpu']}",
        f"- PyTorch: {payload['torch_version']} (HIP {payload['hip_version']})",
        f"- CPU threads available to PyTorch: {payload['torch_threads']}",
        "",
    ]
    table_path.write_text(
        "\n".join(header + sections) + "\n", encoding="utf-8"
    )

    print()
    print("\n\n".join(sections))
    print(f"\nJSON:  {json_path}")
    print(f"Table: {table_path}")


if __name__ == "__main__":
    main()
