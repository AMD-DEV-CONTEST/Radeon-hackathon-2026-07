"""Produce per-scenario diagnostics for a held-out nuScenes hybrid model."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch

from chronosafe.models.compositional_gru import CompositionalHealthGRU
from train_hybrid_nuscenes_gru import (
    SCENARIO_ORDER,
    composed_predictions,
    conformal_quantile,
    load_real_split_file,
    make_loader,
    make_sequences,
    predict,
    sha256_file,
    source_metrics,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/chronosafe_nuscenes_mini.npz"))
    parser.add_argument("--model", type=Path, default=Path("artifacts/hybrid_nuscenes_gru/model.pt"))
    parser.add_argument("--output", type=Path, default=Path("results/hybrid_nuscenes_evaluation"))
    parser.add_argument("--test-scene-count", type=int, default=2)
    parser.add_argument(
        "--split-file",
        type=Path,
        default=None,
        help="Use the test scenes from a frozen train/calibration/test manifest.",
    )
    parser.add_argument(
        "--recalibrate",
        action="store_true",
        help="Recompute a robust conformal radius from the manifest calibration scenes.",
    )
    parser.add_argument(
        "--exclude-logs-containing-scenes-from",
        type=Path,
        default=None,
        help="Exclude full target-data logs containing scenes listed in another dataset manifest.",
    )
    parser.add_argument("--sequence-length", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--dpi", type=int, default=180)
    return parser.parse_args()


def excluded_log_scene_ids(
    target_metadata_path: Path,
    exclusion_metadata_path: Path,
) -> tuple[set[int], set[str], set[str]]:
    target = json.loads(target_metadata_path.read_text(encoding="utf-8"))
    exclusion = json.loads(exclusion_metadata_path.read_text(encoding="utf-8"))
    exclusion_tokens = {
        str(scene["scene_token"]) for scene in exclusion.get("scenes", [])
    }
    target_scenes = target.get("scenes", [])
    overlapping_tokens = {
        str(scene["scene_token"])
        for scene in target_scenes
        if str(scene["scene_token"]) in exclusion_tokens
    }
    excluded_logs = {
        str(scene["log_token"])
        for scene in target_scenes
        if str(scene["scene_token"]) in overlapping_tokens
    }
    excluded_scene_ids = {
        int(scene["scene_id"])
        for scene in target_scenes
        if str(scene["log_token"]) in excluded_logs
    }
    return excluded_scene_ids, excluded_logs, overlapping_tokens


def plot_confusion(matrix: np.ndarray, output: Path, dpi: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    totals = np.maximum(matrix.sum(axis=1, keepdims=True), 1)
    normalized = matrix / totals
    labels = [name.replace("_", " ") for name in SCENARIO_ORDER]
    figure, axis = plt.subplots(figsize=(9.4, 8.0))
    image = axis.imshow(normalized, cmap="Blues", vmin=0.0, vmax=1.0)
    axis.set_xticks(range(len(labels)), labels=labels, rotation=32, ha="right")
    axis.set_yticks(range(len(labels)), labels=labels)
    axis.set_xlabel("Predicted scenario")
    axis.set_ylabel("Ground-truth scenario")
    axis.set_title("ChronoSafe-Drive: Held-Out nuScenes Scenario Diagnosis")
    axis.grid(False)
    for row in range(len(labels)):
        for column in range(len(labels)):
            value = normalized[row, column]
            axis.text(
                column,
                row,
                f"{matrix[row, column]}\n{value:.0%}",
                ha="center",
                va="center",
                color="white" if value > 0.52 else "#111827",
                fontsize=8,
            )
    figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04, label="Row-normalized rate")
    figure.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available() or torch.version.hip is None:
        raise RuntimeError("AMD ROCm GPU is required for evaluation evidence")
    device = torch.device("cuda")
    checkpoint = torch.load(args.model, map_location=device, weights_only=False)
    model = CompositionalHealthGRU(checkpoint["input_size"], checkpoint["hidden_size"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    payload = np.load(args.data)
    scene_ids = payload["scene_ids"]
    unique_scenes = sorted(int(value) for value in np.unique(scene_ids))
    calibration_scenes: list[int] = []
    if args.split_file is not None:
        _, calibration_scenes, test_scenes = load_real_split_file(args.split_file)
        if not set(calibration_scenes + test_scenes).issubset(unique_scenes):
            raise ValueError("Split manifest references scenes absent from the evaluation data")
    else:
        if args.test_scene_count < 1 or len(unique_scenes) <= args.test_scene_count:
            raise ValueError("Invalid --test-scene-count")
        test_scenes = unique_scenes[-args.test_scene_count :]
    if args.recalibrate and args.split_file is None:
        raise ValueError("--recalibrate requires --split-file")
    excluded_scene_ids: set[int] = set()
    excluded_logs: set[str] = set()
    overlapping_scene_tokens: set[str] = set()
    if args.exclude_logs_containing_scenes_from is not None:
        target_metadata_path = args.data.with_suffix(".json")
        if not target_metadata_path.is_file():
            raise FileNotFoundError(f"Target dataset metadata is missing: {target_metadata_path}")
        excluded_scene_ids, excluded_logs, overlapping_scene_tokens = excluded_log_scene_ids(
            target_metadata_path,
            args.exclude_logs_containing_scenes_from,
        )
        calibration_scenes = [
            scene for scene in calibration_scenes if scene not in excluded_scene_ids
        ]
        test_scenes = [scene for scene in test_scenes if scene not in excluded_scene_ids]
        if args.recalibrate and not calibration_scenes:
            raise ValueError("Log exclusion removed every calibration scene")
        if not test_scenes:
            raise ValueError("Log exclusion removed every test scene")
    sequence_length = args.sequence_length or int(checkpoint["sequence_length"])
    x, y, risk, domains = make_sequences(
        payload["features"],
        payload["labels"],
        payload["risks"],
        payload["track_ids"],
        scene_ids,
        test_scenes,
        sequence_length,
    )
    mean = np.asarray(checkpoint["feature_mean"], dtype=np.float32)
    std = np.asarray(checkpoint["feature_std"], dtype=np.float32)
    loader = make_loader((x - mean) / std, y, risk, args.batch_size, False)
    result = predict(model, loader, device)
    scenario_hat = composed_predictions(result)
    domain_radii: dict[str, float] = {}
    if args.recalibrate:
        calibration_x, calibration_y, calibration_risk, calibration_domains = make_sequences(
            payload["features"],
            payload["labels"],
            payload["risks"],
            payload["track_ids"],
            scene_ids,
            calibration_scenes,
            sequence_length,
        )
        calibration_loader = make_loader(
            (calibration_x - mean) / std,
            calibration_y,
            calibration_risk,
            args.batch_size,
            False,
        )
        calibration_result = predict(model, calibration_loader, device)
        residuals = np.abs(calibration_result["risk"] - calibration_result["risk_hat"])
        for domain in np.unique(calibration_domains):
            domain_radii[str(int(domain))] = conformal_quantile(
                residuals[calibration_domains == domain], 0.1
            )
        radius = max(domain_radii.values())
        calibration_source = "split calibration scenes"
    else:
        radius = float(checkpoint["conformal_radius"])
        calibration_source = "checkpoint"

    matrix = np.zeros((len(SCENARIO_ORDER), len(SCENARIO_ORDER)), dtype=np.int64)
    for truth, prediction in zip(result["scenario"], scenario_hat, strict=True):
        matrix[int(truth), int(prediction)] += 1

    per_scenario: dict[str, dict[str, float | int]] = {}
    for index, name in enumerate(SCENARIO_ORDER):
        mask = result["scenario"] == index
        per_scenario[name] = {
            "sequences": int(mask.sum()),
            "scenario_accuracy": round(float(np.mean(scenario_hat[mask] == index)), 6),
            "camera_accuracy": round(float(np.mean(result["camera_hat"][mask] == result["camera"][mask])), 6),
            "lidar_accuracy": round(float(np.mean(result["lidar_hat"][mask] == result["lidar"][mask])), 6),
            "delay_accuracy": round(float(np.mean(result["delay_hat"][mask] == result["delay"][mask])), 6),
            "risk_mae": round(float(np.mean(np.abs(result["risk"][mask] - result["risk_hat"][mask]))), 6),
            "upper_risk_coverage": round(
                float(np.mean(result["risk"][mask] <= result["risk_hat"][mask] + radius)), 6
            ),
        }

    per_scene: dict[str, dict[str, float | int]] = {}
    for domain in np.unique(domains):
        mask = domains == domain
        scene_result = {key: value[mask] for key, value in result.items()}
        per_scene[str(int(domain))] = source_metrics(scene_result, radius)

    summary = {
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0),
        "hip": torch.version.hip,
        "model": str(args.model),
        "split_file": str(args.split_file) if args.split_file else None,
        "split_sha256": sha256_file(args.split_file) if args.split_file else None,
        "exclusion_manifest": (
            str(args.exclude_logs_containing_scenes_from)
            if args.exclude_logs_containing_scenes_from
            else None
        ),
        "exclusion_manifest_sha256": (
            sha256_file(args.exclude_logs_containing_scenes_from)
            if args.exclude_logs_containing_scenes_from
            else None
        ),
        "excluded_overlapping_scene_tokens": sorted(overlapping_scene_tokens),
        "excluded_log_tokens": sorted(excluded_logs),
        "excluded_scene_ids": sorted(excluded_scene_ids),
        "calibration_scene_count": len(calibration_scenes),
        "test_scene_count": len(test_scenes),
        "test_scenes": test_scenes,
        "sequences": int(len(y)),
        "scenario_accuracy": round(float(np.mean(result["scenario"] == scenario_hat)), 6),
        "conformal_radius": round(radius, 6),
        "calibration_source": calibration_source,
        "domain_calibration_radii": {
            key: round(value, 6) for key, value in domain_radii.items()
        },
        "overall": source_metrics(result, radius),
        "per_scenario": per_scenario,
        "per_scene": per_scene,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (args.output / "confusion_matrix.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ground_truth/prediction", *SCENARIO_ORDER])
        for name, row in zip(SCENARIO_ORDER, matrix, strict=True):
            writer.writerow([name, *row.tolist()])
    plot_confusion(matrix, args.output / "nuScenes_confusion_matrix.png", args.dpi)
    console_summary = {
        key: value
        for key, value in summary.items()
        if key
        not in {
            "test_scenes",
            "domain_calibration_radii",
            "per_scene",
            "excluded_overlapping_scene_tokens",
            "excluded_log_tokens",
            "excluded_scene_ids",
        }
    }
    print(json.dumps(console_summary, indent=2))
    print(f"evaluation: {args.output}")
    print("ROCm hybrid nuScenes evaluation: PASS")


if __name__ == "__main__":
    main()
