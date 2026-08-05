"""Benchmark ChronoSafe-Drive inference on an AMD ROCm GPU using real test sequences.

The benchmark deliberately excludes dataset loading and host-to-device transfer from
the timed region. It measures the deployed, device-resident perception-health model
forward pass and separately verifies AMP predictions against the FP32 reference.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch

from chronosafe.models.compositional_gru import CompositionalHealthGRU
from train_hybrid_nuscenes_gru import load_real_split_file, make_sequences


PRECISIONS = ("fp32", "amp_fp16")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("data/chronosafe_nuscenes_trainval_timing_v3.npz"),
    )
    parser.add_argument(
        "--split-file",
        type=Path,
        default=Path("configs/nuscenes_trainval_v3_split.json"),
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/rocm_inference_benchmark"),
    )
    parser.add_argument("--batch-sizes", default="1,32,256,1024")
    parser.add_argument("--warmup-iterations", type=int, default=50)
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--verification-samples", type=int, default=8192)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--agreement-threshold", type=float, default=0.999)
    parser.add_argument("--risk-error-threshold", type=float, default=0.005)
    parser.add_argument("--dpi", type=int, default=200)
    return parser.parse_args()


def parse_batch_sizes(value: str) -> list[int]:
    batch_sizes = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not batch_sizes or any(size < 1 for size in batch_sizes):
        raise ValueError("--batch-sizes must contain positive integers")
    if len(batch_sizes) != len(set(batch_sizes)):
        raise ValueError("--batch-sizes contains duplicates")
    return batch_sizes


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def amp_context(precision: str):
    if precision == "amp_fp16":
        return torch.autocast(device_type="cuda", dtype=torch.float16)
    return nullcontext()


def forward(
    model: CompositionalHealthGRU,
    inputs: torch.Tensor,
    precision: str,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    with torch.inference_mode(), amp_context(precision):
        return model(inputs)


def benchmark_one(
    model: CompositionalHealthGRU,
    inputs: torch.Tensor,
    precision: str,
    warmup_iterations: int,
    iterations: int,
) -> dict[str, float | int | str]:
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    baseline_allocated = torch.cuda.memory_allocated()
    baseline_reserved = torch.cuda.memory_reserved()

    output_dtype = ""
    for _ in range(warmup_iterations):
        outputs = forward(model, inputs, precision)
        output_dtype = str(outputs[0].dtype).replace("torch.", "")
        del outputs
    torch.cuda.synchronize()

    elapsed_ms: list[float] = []
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    for _ in range(iterations):
        start.record()
        outputs = forward(model, inputs, precision)
        end.record()
        end.synchronize()
        elapsed_ms.append(float(start.elapsed_time(end)))
        del outputs
    torch.cuda.synchronize()

    values = np.asarray(elapsed_ms, dtype=np.float64)
    mean_ms = float(values.mean())
    return {
        "precision": precision,
        "output_dtype": output_dtype,
        "batch_size": int(inputs.shape[0]),
        "warmup_iterations": warmup_iterations,
        "iterations": iterations,
        "latency_mean_ms": round(mean_ms, 6),
        "latency_std_ms": round(float(values.std(ddof=1)), 6),
        "latency_p50_ms": round(float(np.percentile(values, 50)), 6),
        "latency_p95_ms": round(float(np.percentile(values, 95)), 6),
        "latency_p99_ms": round(float(np.percentile(values, 99)), 6),
        "throughput_sequences_per_s": round(float(inputs.shape[0]) * 1000.0 / mean_ms, 2),
        "baseline_allocated_mib": round(baseline_allocated / 2**20, 3),
        "baseline_reserved_mib": round(baseline_reserved / 2**20, 3),
        "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 2**20, 3),
        "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 2**20, 3),
        "incremental_peak_allocated_mib": round(
            (torch.cuda.max_memory_allocated() - baseline_allocated) / 2**20, 3
        ),
    }


def batched_predictions(
    model: CompositionalHealthGRU,
    inputs: torch.Tensor,
    precision: str,
    batch_size: int,
) -> dict[str, np.ndarray | str]:
    camera: list[np.ndarray] = []
    lidar: list[np.ndarray] = []
    delay: list[np.ndarray] = []
    risks: list[np.ndarray] = []
    output_dtype = ""
    for start in range(0, len(inputs), batch_size):
        outputs = forward(model, inputs[start : start + batch_size], precision)
        output_dtype = str(outputs[0].dtype).replace("torch.", "")
        camera.append(outputs[0].argmax(dim=1).cpu().numpy())
        lidar.append(outputs[1].argmax(dim=1).cpu().numpy())
        delay.append(outputs[2].argmax(dim=1).cpu().numpy())
        risks.append(outputs[3].float().cpu().numpy())
        del outputs
    return {
        "camera": np.concatenate(camera),
        "lidar": np.concatenate(lidar),
        "delay": np.concatenate(delay),
        "risk": np.concatenate(risks),
        "output_dtype": output_dtype,
    }


def verify_amp(
    model: CompositionalHealthGRU,
    inputs: torch.Tensor,
    batch_size: int,
    agreement_threshold: float,
    risk_error_threshold: float,
) -> dict[str, float | int | bool | str]:
    fp32 = batched_predictions(model, inputs, "fp32", batch_size)
    amp = batched_predictions(model, inputs, "amp_fp16", batch_size)
    camera_equal = np.asarray(fp32["camera"]) == np.asarray(amp["camera"])
    lidar_equal = np.asarray(fp32["lidar"]) == np.asarray(amp["lidar"])
    delay_equal = np.asarray(fp32["delay"]) == np.asarray(amp["delay"])
    joint_equal = camera_equal & lidar_equal & delay_equal
    risk_error = np.abs(np.asarray(fp32["risk"]) - np.asarray(amp["risk"]))
    joint_agreement = float(joint_equal.mean())
    max_risk_error = float(risk_error.max())
    passed = joint_agreement >= agreement_threshold and max_risk_error <= risk_error_threshold
    return {
        "samples": int(len(inputs)),
        "comparison_batch_size": batch_size,
        "fp32_output_dtype": str(fp32["output_dtype"]),
        "amp_output_dtype": str(amp["output_dtype"]),
        "camera_classification_agreement": round(float(camera_equal.mean()), 8),
        "lidar_classification_agreement": round(float(lidar_equal.mean()), 8),
        "delay_classification_agreement": round(float(delay_equal.mean()), 8),
        "joint_factor_classification_agreement": round(joint_agreement, 8),
        "risk_mean_absolute_error": round(float(risk_error.mean()), 8),
        "risk_p99_absolute_error": round(float(np.percentile(risk_error, 99)), 8),
        "risk_max_absolute_error": round(max_risk_error, 8),
        "agreement_threshold": agreement_threshold,
        "risk_error_threshold": risk_error_threshold,
        "passed": passed,
    }


def hardware_info() -> dict[str, Any]:
    properties = torch.cuda.get_device_properties(0)
    gcn_arch = getattr(properties, "gcnArchName", None)
    return {
        "gpu_name": torch.cuda.get_device_name(0),
        "gcn_arch": gcn_arch,
        "device_capability": list(torch.cuda.get_device_capability(0)),
        "total_vram_gib": round(properties.total_memory / 2**30, 3),
        "multiprocessor_count": getattr(properties, "multi_processor_count", None),
        "torch_version": str(torch.__version__),
        "hip_version": str(torch.version.hip),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "rocr_visible_devices": os.environ.get("ROCR_VISIBLE_DEVICES"),
        "hip_visible_devices": os.environ.get("HIP_VISIBLE_DEVICES"),
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(report: dict[str, Any], path: Path) -> None:
    hardware = report["hardware"]
    verification = report["amp_verification"]
    lines = [
        "# ChronoSafe-Drive AMD ROCm Inference Benchmark",
        "",
        "This benchmark uses frozen, held-out nuScenes temporal sequences. Timings cover "
        "device-resident model forward inference; dataset loading and host-to-device transfer "
        "are excluded.",
        "",
        "## Environment",
        "",
        f"- GPU: {hardware['gpu_name']} ({hardware.get('gcn_arch')})",
        f"- ROCm/HIP: {hardware['hip_version']}",
        f"- PyTorch: {hardware['torch_version']}",
        f"- VRAM: {hardware['total_vram_gib']} GiB",
        f"- Test sequences available: {report['dataset']['test_sequences']:,}",
        f"- Model parameters: {report['model']['parameters']:,}",
        "",
        "## Latency and throughput",
        "",
        "| Precision | Batch | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (seq/s) | Peak allocated (MiB) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["benchmarks"]:
        lines.append(
            f"| {row['precision']} | {row['batch_size']} | {row['latency_p50_ms']:.6f} | "
            f"{row['latency_p95_ms']:.6f} | {row['latency_p99_ms']:.6f} | "
            f"{row['throughput_sequences_per_s']:,.2f} | {row['peak_allocated_mib']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## FP32 versus AMP numerical verification",
            "",
            f"- Samples: {verification['samples']:,}",
            f"- Joint camera/LiDAR/delay classification agreement: "
            f"{verification['joint_factor_classification_agreement']:.6%}",
            f"- Risk mean absolute error: {verification['risk_mean_absolute_error']:.8f}",
            f"- Risk maximum absolute error: {verification['risk_max_absolute_error']:.8f}",
            f"- Verification: {'PASS' if verification['passed'] else 'FAIL'}",
            "",
            "## AMP speedup over FP32",
            "",
            "| Batch | p50 latency speedup | Throughput speedup |",
            "|---:|---:|---:|",
        ]
    )
    for item in report["speedups"]:
        lines.append(
            f"| {item['batch_size']} | {item['p50_latency_speedup']:.3f}x | "
            f"{item['throughput_speedup']:.3f}x |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_results(report: dict[str, Any], path: Path, dpi: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = report["benchmarks"]
    figure, axes = plt.subplots(1, 2, figsize=(12.5, 4.8))
    colors = {"fp32": "#2563eb", "amp_fp16": "#dc2626"}
    labels = {"fp32": "FP32", "amp_fp16": "ROCm AMP (FP16)"}
    for precision in PRECISIONS:
        selected = [row for row in rows if row["precision"] == precision]
        batches = [row["batch_size"] for row in selected]
        axes[0].plot(
            batches,
            [row["latency_p50_ms"] for row in selected],
            marker="o",
            linewidth=2,
            color=colors[precision],
            label=labels[precision],
        )
        axes[1].plot(
            batches,
            [row["throughput_sequences_per_s"] for row in selected],
            marker="o",
            linewidth=2,
            color=colors[precision],
            label=labels[precision],
        )
    for axis in axes:
        axis.set_xscale("log", base=2)
        axis.set_xticks(report["protocol"]["batch_sizes"])
        axis.set_xticklabels([str(value) for value in report["protocol"]["batch_sizes"]])
        axis.grid(True, which="both", alpha=0.25)
        axis.legend(frameon=False)
        axis.set_xlabel("Batch size (real nuScenes sequences)")
    axes[0].set_yscale("log")
    axes[0].set_ylabel("p50 latency (ms, log scale)")
    axes[0].set_title("Device-resident inference latency")
    axes[1].set_yscale("log")
    axes[1].set_ylabel("Throughput (sequences/s, log scale)")
    axes[1].set_title("AMD Radeon ROCm throughput")
    figure.suptitle("ChronoSafe-Drive: FP32 vs ROCm AMP", fontweight="bold")
    figure.tight_layout()
    figure.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("A GPU is required; torch.cuda.is_available() returned False")
    if torch.version.hip is None:
        raise RuntimeError("AMD ROCm/HIP PyTorch is required; torch.version.hip is None")
    if args.warmup_iterations < 1 or args.iterations < 10:
        raise ValueError("Use at least 1 warmup and 10 timed iterations")
    if args.verification_samples < 1:
        raise ValueError("--verification-samples must be positive")
    batch_sizes = parse_batch_sizes(args.batch_sizes)
    for path in (args.data, args.split_file, args.model):
        if not path.is_file():
            raise FileNotFoundError(path)

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device("cuda:0")
    checkpoint = torch.load(args.model, map_location=device, weights_only=False)
    model = CompositionalHealthGRU(
        int(checkpoint["input_size"]), int(checkpoint["hidden_size"])
    ).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    payload = np.load(args.data)
    _, _, test_scenes = load_real_split_file(args.split_file)
    x, y, risk, domains = make_sequences(
        payload["features"],
        payload["labels"],
        payload["risks"],
        payload["track_ids"],
        payload["scene_ids"],
        test_scenes,
        int(checkpoint["sequence_length"]),
    )
    mean = np.asarray(checkpoint["feature_mean"], dtype=np.float32)
    std = np.asarray(checkpoint["feature_std"], dtype=np.float32)
    normalized = np.ascontiguousarray((x - mean) / std, dtype=np.float32)
    largest_batch = max(batch_sizes)
    if len(normalized) >= largest_batch:
        benchmark_array = normalized[:largest_batch]
    else:
        repeats = (largest_batch + len(normalized) - 1) // len(normalized)
        benchmark_array = np.tile(normalized, (repeats, 1, 1))[:largest_batch]
    benchmark_sequences = torch.from_numpy(
        np.ascontiguousarray(benchmark_array)
    ).to(device)

    rows: list[dict[str, Any]] = []
    for precision in PRECISIONS:
        for batch_size in batch_sizes:
            inputs = benchmark_sequences[:batch_size]
            row = benchmark_one(
                model,
                inputs,
                precision,
                args.warmup_iterations,
                args.iterations,
            )
            rows.append(row)
            print(
                f"{precision:>9} batch={batch_size:4d} "
                f"p50={row['latency_p50_ms']:.6f} ms "
                f"throughput={row['throughput_sequences_per_s']:,.2f} seq/s"
            )

    verification_count = min(args.verification_samples, len(normalized))
    rng = np.random.default_rng(args.seed)
    verification_indices = np.sort(
        rng.choice(len(normalized), size=verification_count, replace=False)
    )
    verification_tensor = torch.from_numpy(
        np.ascontiguousarray(normalized[verification_indices])
    ).to(device)
    verification = verify_amp(
        model,
        verification_tensor,
        max(batch_sizes),
        args.agreement_threshold,
        args.risk_error_threshold,
    )

    by_key = {(row["precision"], row["batch_size"]): row for row in rows}
    speedups = []
    for batch_size in batch_sizes:
        fp32 = by_key[("fp32", batch_size)]
        amp = by_key[("amp_fp16", batch_size)]
        speedups.append(
            {
                "batch_size": batch_size,
                "p50_latency_speedup": round(
                    fp32["latency_p50_ms"] / amp["latency_p50_ms"], 6
                ),
                "throughput_speedup": round(
                    amp["throughput_sequences_per_s"] / fp32["throughput_sequences_per_s"],
                    6,
                ),
            }
        )

    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    report: dict[str, Any] = {
        "benchmark": "ChronoSafe-Drive AMD ROCm real-data inference",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if verification["passed"] else "FAIL",
        "scope": "device-resident model forward; excludes data loading and H2D transfer",
        "hardware": hardware_info(),
        "model": {
            "path": str(args.model),
            "sha256": sha256_file(args.model),
            "model_type": checkpoint.get("model_type"),
            "input_size": int(checkpoint["input_size"]),
            "hidden_size": int(checkpoint["hidden_size"]),
            "sequence_length": int(checkpoint["sequence_length"]),
            "parameters": parameter_count,
        },
        "dataset": {
            "path": str(args.data),
            "sha256": sha256_file(args.data),
            "split_file": str(args.split_file),
            "split_sha256": sha256_file(args.split_file),
            "test_scene_count": len(test_scenes),
            "test_scenes": test_scenes,
            "test_sequences": int(len(x)),
            "feature_shape": list(x.shape),
            "scenario_count": int(len(np.unique(y))),
            "domain_count": int(len(np.unique(domains))),
            "risk_range": [round(float(risk.min()), 6), round(float(risk.max()), 6)],
        },
        "protocol": {
            "seed": args.seed,
            "precisions": list(PRECISIONS),
            "batch_sizes": batch_sizes,
            "warmup_iterations": args.warmup_iterations,
            "timed_iterations": args.iterations,
            "timing": "torch.cuda.Event on ROCm, synchronized after each forward",
        },
        "benchmarks": rows,
        "speedups": speedups,
        "amp_verification": verification,
    }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "benchmark.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    write_csv(rows, args.output / "benchmark.csv")
    write_markdown(report, args.output / "benchmark.md")
    plot_results(report, args.output / "benchmark.png", args.dpi)
    print(json.dumps({"status": report["status"], "amp_verification": verification}, indent=2))
    print(f"results: {args.output}")
    if not verification["passed"]:
        raise RuntimeError("ROCm AMP numerical verification failed")
    print("ChronoSafe AMD ROCm inference benchmark: PASS")


if __name__ == "__main__":
    main()
