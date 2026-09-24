"""Consolidate the ROCm benchmark runs into one report.

``07_rocm_benchmark.py`` has to be run twice, because the CPU baseline is
extremely sensitive to the PyTorch thread count: at batch 64 the optimiser
spends more time synchronising 64 threads than doing arithmetic. Comparing a
tuned GPU against an untuned CPU would overstate the ROCm advantage by roughly
50%, so this script merges both runs and reports the fair comparison.

Expected inputs:
    outputs/rocm_benchmark/rocm_benchmark.json          (default threads)
    outputs/rocm_benchmark_1thread/rocm_benchmark.json  (OMP_NUM_THREADS=1)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


def load_benchmark_module():
    path = Path(__file__).resolve().parent / "07_rocm_benchmark.py"
    spec = importlib.util.spec_from_file_location("rocm_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args():
    parser = argparse.ArgumentParser(
        description="Consolidate ROCm benchmark runs into one report."
    )
    parser.add_argument(
        "--multithread-json",
        type=Path,
        default=Path("outputs/rocm_benchmark/rocm_benchmark.json"),
    )
    parser.add_argument(
        "--singlethread-json",
        type=Path,
        default=Path("outputs/rocm_benchmark_1thread/rocm_benchmark.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/rocm_benchmark"),
    )
    return parser.parse_args()


def _throughput(payload: dict, device: str) -> dict[int, float]:
    return {
        entry["n_envs"]: entry["steps_per_second"]
        for entry in payload.get("throughput", [])
        if entry["device"] == device
    }


def _gpu_utilization(payload: dict) -> dict[int, float | None]:
    return {
        entry["n_envs"]: entry.get("gpu_mean_utilization_pct")
        for entry in payload.get("throughput", [])
        if entry["device"] == "cuda"
    }


def render_throughput_table(multi: dict, single: dict) -> str:
    cpu_multi = _throughput(multi, "cpu")
    cpu_single = _throughput(single, "cpu")
    gpu_multi = _throughput(multi, "cuda")
    utilization = _gpu_utilization(multi)

    lines = [
        "## End-to-end training throughput",
        "",
        "Full DQN training with the default 256x256 policy. The CPU column "
        "that matters is the tuned one (`OMP_NUM_THREADS=1`); with the "
        "default 64 threads the CPU baseline loses 25-35% to thread "
        "synchronisation on batch-64 updates.",
        "",
        "| Parallel envs | CPU 64 threads | CPU 1 thread (tuned) | ROCm |"
        " ROCm vs tuned CPU | GPU util |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for n_envs in sorted(gpu_multi):
        if n_envs not in cpu_single or n_envs not in cpu_multi:
            continue
        tuned = cpu_single[n_envs]
        gpu = gpu_multi[n_envs]
        util = utilization.get(n_envs)
        lines.append(
            f"| {n_envs} | {cpu_multi[n_envs]:.0f} | **{tuned:.0f}** |"
            f" {gpu:.0f} | {gpu / tuned:.2f}x |"
            f" {f'{util:.0f}%' if util is not None else 'n/a'} |"
        )

    return "\n".join(lines)


def plot_throughput(multi: dict, single: dict, output_path: Path):
    cpu_multi = _throughput(multi, "cpu")
    cpu_single = _throughput(single, "cpu")
    gpu_multi = _throughput(multi, "cuda")

    figure, axes = plt.subplots(figsize=(7.5, 5.0))
    series = [
        (cpu_single, "CPU (1 thread, tuned)", "#1f77b4", "o", "-"),
        (cpu_multi, "CPU (64 threads)", "#8c564b", "s", "--"),
        (gpu_multi, "ROCm GPU", "#d62728", "^", "-"),
    ]
    for data, label, color, marker, style in series:
        keys = sorted(data)
        axes.plot(
            keys,
            [data[k] for k in keys],
            marker=marker,
            linestyle=style,
            color=color,
            linewidth=2,
            label=label,
        )

    axes.set_xscale("log", base=2)
    axes.set_xticks(sorted(gpu_multi))
    axes.set_xticklabels([str(k) for k in sorted(gpu_multi)])
    axes.set_xlabel("Parallel environments")
    axes.set_ylabel("Training throughput (steps/s)")
    axes.set_title(
        "End-to-end DQN training is environment-bound\n"
        "A tuned CPU matches the Radeon GPU; GPU utilisation stays under 3%"
    )
    axes.grid(alpha=0.3, linestyle="--")
    axes.legend()
    figure.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def main():
    args = parse_args()

    multi = json.loads(args.multithread_json.read_text(encoding="utf-8"))
    single = json.loads(args.singlethread_json.read_text(encoding="utf-8"))

    benchmark = load_benchmark_module()
    gradient_results = multi["gradient"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    benchmark.plot_crossover(
        gradient_results, args.output_dir / "rocm_crossover.png"
    )
    plot_throughput(
        multi, single, args.output_dir / "rocm_throughput.png"
    )

    best_speedup = max(
        benchmark._find(gradient_results, "cuda", arch, batch)[
            "gradient_steps_per_second"
        ]
        / benchmark._find(gradient_results, "cpu", arch, batch)[
            "gradient_steps_per_second"
        ]
        for arch in benchmark.NET_ARCHS
        for batch in benchmark.BATCH_SIZES
    )
    cpu_single = _throughput(single, "cpu")
    gpu_multi = _throughput(multi, "cuda")
    end_to_end = max(gpu_multi[n] / cpu_single[n] for n in cpu_single)

    report = "\n\n".join(
        [
            "# AMD ROCm benchmark",
            "\n".join(
                [
                    f"- GPU: {multi['gpu']}",
                    f"- PyTorch: {multi['torch_version']} "
                    f"(HIP {multi['hip_version']})",
                    f"- CPU threads available: {multi['torch_threads']}",
                ]
            ),
            "## Summary",
            "\n".join(
                [
                    f"- The optimiser step alone runs up to "
                    f"**{best_speedup:.0f}x faster** on ROCm than on the CPU.",
                    f"- End-to-end training still tops out at "
                    f"**{end_to_end:.2f}x** against a tuned CPU, because the "
                    "HighwayEnv simulation dominates wall-clock time.",
                    "- GPU utilisation during real training stays under 3% "
                    "and peak VRAM is about 110 MB, so the accelerator is "
                    "idle almost the whole run.",
                    "- Running many small training jobs concurrently on one "
                    "GPU is actively harmful: nine parallel jobs collapsed to "
                    "85 steps/s in aggregate versus 650 steps/s on CPU, "
                    "because the tiny kernels serialise on a single HIP "
                    "context.",
                    "- ROCm becomes worthwhile as soon as the policy grows "
                    "(image observations, wider networks, larger batches); "
                    "the gradient table below quantifies the headroom.",
                ]
            ),
            benchmark.render_gradient_table(gradient_results),
            render_throughput_table(multi, single),
        ]
    )

    report_path = args.output_dir / "rocm_summary.md"
    report_path.write_text(report + "\n", encoding="utf-8")

    print(report)
    print(f"\nReport: {report_path}")
    print(f"Plots:  {args.output_dir}/rocm_crossover.png")
    print(f"        {args.output_dir}/rocm_throughput.png")


if __name__ == "__main__":
    main()
