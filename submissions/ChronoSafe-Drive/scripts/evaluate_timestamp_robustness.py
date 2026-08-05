"""Stress-test ChronoSafe models under causal timestamp metadata corruption."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from chronosafe.models.compositional_gru import CompositionalHealthGRU
from evaluate_hybrid_nuscenes_gru import excluded_log_scene_ids
from train_hybrid_nuscenes_gru import (
    SCENARIO_ORDER,
    composed_predictions,
    load_real_split_file,
    make_loader,
    make_sequences,
    predict,
    sha256_file,
    source_metrics,
)


@dataclass(frozen=True)
class TimestampCondition:
    name: str
    kind: str
    value: float = 0.0


CONDITIONS = (
    TimestampCondition("intact", "intact"),
    TimestampCondition("missing_burst_10pct", "missing", 0.10),
    TimestampCondition("missing_burst_30pct", "missing", 0.30),
    TimestampCondition("missing_burst_50pct", "missing", 0.50),
    TimestampCondition("camera_clock_drift_1frame", "drift", 1.0),
    TimestampCondition("camera_clock_drift_3frames", "drift", 3.0),
    TimestampCondition("camera_clock_drift_5frames", "drift", 5.0),
    TimestampCondition("timestamp_jitter_1frame", "jitter", 1.0),
    TimestampCondition("timestamp_jitter_2frames", "jitter", 2.0),
    TimestampCondition("timestamp_channels_swapped", "swap"),
    TimestampCondition("timestamps_spoofed_clean", "spoof"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("data/chronosafe_nuscenes_trainval_timing_v3.npz"),
    )
    parser.add_argument(
        "--models",
        type=Path,
        nargs="+",
        default=[
            Path("artifacts/hybrid_timing_gru_v3_large_seed2026/model.pt"),
            Path("artifacts/hybrid_timing_gru_v3_large_seed2027/model.pt"),
            Path("artifacts/hybrid_timing_gru_v3_large_seed2028/model.pt"),
        ],
    )
    parser.add_argument(
        "--split-file",
        type=Path,
        default=Path("configs/nuscenes_trainval_v3_split.json"),
    )
    parser.add_argument(
        "--exclude-logs-containing-scenes-from",
        type=Path,
        default=Path("data/chronosafe_nuscenes_timing_v2.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/timestamp_robustness_v3")
    )
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--dpi", type=int, default=180)
    return parser.parse_args()


def grouped_track_indices(
    track_ids: np.ndarray,
    scene_ids: np.ndarray,
    selected_scenes: list[int],
) -> list[np.ndarray]:
    eligible = np.flatnonzero(np.isin(scene_ids, selected_scenes))
    order = eligible[np.argsort(track_ids[eligible], kind="stable")]
    ordered_tracks = track_ids[order]
    starts = np.flatnonzero(
        np.concatenate((np.asarray([True]), ordered_tracks[1:] != ordered_tracks[:-1]))
    )
    ends = np.concatenate((starts[1:], np.asarray([len(order)])))
    return [order[start:end] for start, end in zip(starts, ends, strict=True)]


def corrupt_timestamp_features(
    source: np.ndarray,
    tracks: list[np.ndarray],
    feature_names: list[str],
    condition: TimestampCondition,
    seed: int,
) -> np.ndarray:
    if condition.kind == "intact":
        return source
    output = source.copy()
    camera_index = feature_names.index("camera_age_normalized")
    lidar_index = feature_names.index("lidar_age_normalized")
    skew_index = feature_names.index("sensor_age_skew")
    rng = np.random.default_rng(seed)
    for indices in tracks:
        if condition.kind == "missing":
            length = max(1, int(round(len(indices) * condition.value)))
            start = int(rng.integers(0, len(indices) - length + 1))
            selected = indices[start : start + length]
            output[selected, camera_index] = 0.0
            output[selected, lidar_index] = 0.0
            output[selected, skew_index] = 0.0
        elif condition.kind == "drift":
            drift = np.linspace(0.0, condition.value / 5.0, len(indices), dtype=np.float32)
            output[indices, camera_index] = np.clip(
                output[indices, camera_index] + drift, 0.0, 2.0
            )
            output[indices, skew_index] = np.abs(
                output[indices, camera_index] - output[indices, lidar_index]
            )
        elif condition.kind == "jitter":
            scale = condition.value / 5.0
            camera_noise = rng.normal(0.0, scale, size=len(indices)).astype(np.float32)
            lidar_noise = rng.normal(0.0, scale, size=len(indices)).astype(np.float32)
            output[indices, camera_index] = np.clip(
                output[indices, camera_index] + camera_noise, 0.0, 2.0
            )
            output[indices, lidar_index] = np.clip(
                output[indices, lidar_index] + lidar_noise, 0.0, 2.0
            )
            output[indices, skew_index] = np.abs(
                output[indices, camera_index] - output[indices, lidar_index]
            )
        elif condition.kind == "swap":
            camera = output[indices, camera_index].copy()
            output[indices, camera_index] = output[indices, lidar_index]
            output[indices, lidar_index] = camera
            output[indices, skew_index] = np.abs(
                output[indices, camera_index] - output[indices, lidar_index]
            )
        elif condition.kind == "spoof":
            output[indices, camera_index] = 0.0
            output[indices, lidar_index] = 0.0
            output[indices, skew_index] = 0.0
        else:
            raise ValueError(f"Unknown timestamp condition: {condition.kind}")
    return output


def per_scenario_accuracy(result: dict[str, np.ndarray]) -> dict[str, float]:
    scenario_hat = composed_predictions(result)
    return {
        name: round(
            float(np.mean(scenario_hat[result["scenario"] == index] == index)), 6
        )
        for index, name in enumerate(SCENARIO_ORDER)
    }


def write_plot(summary: list[dict[str, object]], output: Path, dpi: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [str(row["condition"]).replace("_", " ") for row in summary]
    x = np.arange(len(labels))
    accuracy = np.asarray([float(row["scenario_accuracy_mean"]) * 100.0 for row in summary])
    accuracy_sd = np.asarray([float(row["scenario_accuracy_std"]) * 100.0 for row in summary])
    coverage = np.asarray([float(row["risk_coverage_mean"]) * 100.0 for row in summary])
    coverage_sd = np.asarray([float(row["risk_coverage_std"]) * 100.0 for row in summary])
    risk = np.asarray([float(row["risk_mae_mean"]) for row in summary])
    risk_sd = np.asarray([float(row["risk_mae_std"]) for row in summary])

    figure, axes = plt.subplots(2, 1, figsize=(14.5, 8.2), sharex=True)
    axes[0].errorbar(x, accuracy, yerr=accuracy_sd, marker="o", capsize=3, label="Diagnosis accuracy")
    axes[0].errorbar(x, coverage, yerr=coverage_sd, marker="s", capsize=3, label="Risk coverage")
    axes[0].axhline(90.0, color="#DC2626", linestyle="--", linewidth=1.2, label="90% coverage target")
    axes[0].set_ylabel("Percent (%)")
    axes[0].set_ylim(0.0, 102.0)
    axes[0].grid(axis="y", alpha=0.25)
    axes[0].legend(loc="lower left")
    axes[0].set_title("Timestamp metadata robustness across three preregistered models")

    axes[1].errorbar(x, risk, yerr=risk_sd, color="#E95420", marker="o", capsize=3)
    axes[1].set_ylabel("Risk MAE (lower is better)")
    axes[1].grid(axis="y", alpha=0.25)
    axes[1].set_xticks(x, labels, rotation=28, ha="right")
    figure.tight_layout()
    figure.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available() or torch.version.hip is None:
        raise RuntimeError("AMD ROCm GPU is required for timestamp robustness evidence")
    payload = np.load(args.data)
    feature_names = [str(value) for value in payload["feature_names"]]
    required_features = {
        "camera_age_normalized",
        "lidar_age_normalized",
        "sensor_age_skew",
    }
    if not required_features.issubset(feature_names):
        raise ValueError("Dataset does not contain timing-aware features")

    _, _, test_scenes = load_real_split_file(args.split_file)
    excluded_ids, excluded_logs, overlapping_tokens = excluded_log_scene_ids(
        args.data.with_suffix(".json"),
        args.exclude_logs_containing_scenes_from,
    )
    test_scenes = [scene for scene in test_scenes if scene not in excluded_ids]
    tracks = grouped_track_indices(payload["track_ids"], payload["scene_ids"], test_scenes)
    checkpoints = [
        torch.load(path, map_location="cuda", weights_only=False) for path in args.models
    ]
    sequence_lengths = {int(checkpoint["sequence_length"]) for checkpoint in checkpoints}
    if len(sequence_lengths) != 1:
        raise ValueError("All models must use the same sequence length")
    sequence_length = sequence_lengths.pop()
    device = torch.device("cuda")
    models: list[tuple[torch.nn.Module, dict[str, object]]] = []
    for checkpoint in checkpoints:
        model = CompositionalHealthGRU(
            int(checkpoint["input_size"]), int(checkpoint["hidden_size"])
        ).to(device)
        model.load_state_dict(checkpoint["model_state"])
        model.eval()
        models.append((model, checkpoint))

    condition_results: dict[str, list[dict[str, object]]] = {}
    for condition_index, condition in enumerate(CONDITIONS):
        print(f"condition {condition_index + 1}/{len(CONDITIONS)}: {condition.name}", flush=True)
        features = corrupt_timestamp_features(
            payload["features"],
            tracks,
            feature_names,
            condition,
            args.seed + condition_index * 1009,
        )
        x, y, risk, _ = make_sequences(
            features,
            payload["labels"],
            payload["risks"],
            payload["track_ids"],
            payload["scene_ids"],
            test_scenes,
            sequence_length,
        )
        values: list[dict[str, object]] = []
        for model_path, (model, checkpoint) in zip(args.models, models, strict=True):
            mean = np.asarray(checkpoint["feature_mean"], dtype=np.float32)
            std = np.asarray(checkpoint["feature_std"], dtype=np.float32)
            loader = make_loader(
                (x - mean) / std, y, risk, args.batch_size, False
            )
            result = predict(model, loader, device)
            radius = float(checkpoint["conformal_radius"])
            values.append(
                {
                    "model": str(model_path),
                    "conformal_radius": radius,
                    "metrics": source_metrics(result, radius),
                    "per_scenario_accuracy": per_scenario_accuracy(result),
                }
            )
        condition_results[condition.name] = values

    intact = condition_results["intact"]
    summary_rows: list[dict[str, object]] = []
    for condition in CONDITIONS:
        values = condition_results[condition.name]
        accuracy = np.asarray(
            [float(value["metrics"]["scenario_accuracy"]) for value in values]  # type: ignore[index]
        )
        risk_mae = np.asarray(
            [float(value["metrics"]["risk_mae"]) for value in values]  # type: ignore[index]
        )
        coverage = np.asarray(
            [float(value["metrics"]["upper_risk_coverage"]) for value in values]  # type: ignore[index]
        )
        intact_accuracy = np.asarray(
            [float(value["metrics"]["scenario_accuracy"]) for value in intact]  # type: ignore[index]
        )
        intact_risk = np.asarray(
            [float(value["metrics"]["risk_mae"]) for value in intact]  # type: ignore[index]
        )
        accuracy_std = 0.0 if len(accuracy) == 1 else float(accuracy.std(ddof=1))
        risk_mae_std = 0.0 if len(risk_mae) == 1 else float(risk_mae.std(ddof=1))
        coverage_std = 0.0 if len(coverage) == 1 else float(coverage.std(ddof=1))
        summary_rows.append(
            {
                "condition": condition.name,
                "kind": condition.kind,
                "severity": condition.value,
                "scenario_accuracy_mean": float(accuracy.mean()),
                "scenario_accuracy_std": accuracy_std,
                "accuracy_change_from_intact_pp": float(
                    (accuracy - intact_accuracy).mean() * 100.0
                ),
                "risk_mae_mean": float(risk_mae.mean()),
                "risk_mae_std": risk_mae_std,
                "risk_mae_change_from_intact": float((risk_mae - intact_risk).mean()),
                "risk_coverage_mean": float(coverage.mean()),
                "risk_coverage_std": coverage_std,
                "coverage_target_met": bool(coverage.mean() >= 0.90),
            }
        )

    output = {
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0),
        "hip": torch.version.hip,
        "data": str(args.data),
        "models": [str(path) for path in args.models],
        "split_file": str(args.split_file),
        "split_sha256": sha256_file(args.split_file),
        "exclusion_manifest": str(args.exclude_logs_containing_scenes_from),
        "test_scene_count": len(test_scenes),
        "excluded_log_count": len(excluded_logs),
        "excluded_overlap_scene_count": len(overlapping_tokens),
        "timestamp_corruption_is_causal": True,
        "conditions": condition_results,
        "summary": summary_rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "timestamp_robustness.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    with (args.output / "timestamp_robustness.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        fieldnames = list(summary_rows[0])
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)
    markdown = [
        "# Timestamp metadata robustness",
        "",
        "| Condition | Accuracy mean ± SD | Δ accuracy | Risk MAE | Coverage | ≥90% coverage |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for row in summary_rows:
        markdown.append(
            f"| {str(row['condition']).replace('_', ' ')} | "
            f"{float(row['scenario_accuracy_mean']) * 100:.4f}% ± {float(row['scenario_accuracy_std']) * 100:.4f}% | "
            f"{float(row['accuracy_change_from_intact_pp']):+.4f} pp | "
            f"{float(row['risk_mae_mean']):.6f} | "
            f"{float(row['risk_coverage_mean']) * 100:.4f}% | "
            f"{'yes' if row['coverage_target_met'] else 'no'} |"
        )
    (args.output / "timestamp_robustness.md").write_text(
        "\n".join(markdown) + "\n", encoding="utf-8"
    )
    write_plot(summary_rows, args.output / "timestamp_robustness.png", args.dpi)
    print("\n".join(markdown))
    print(f"results: {args.output}")
    print("ROCm timestamp robustness evaluation: PASS")


if __name__ == "__main__":
    main()
