"""Aggregate fair v2/v3 nuScenes evaluations with log-cluster bootstrap CIs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


METRICS = (
    ("scenario_accuracy", "Scenario accuracy", "higher"),
    ("camera_accuracy", "Camera accuracy", "higher"),
    ("lidar_accuracy", "LiDAR accuracy", "higher"),
    ("delay_accuracy", "Delay accuracy", "higher"),
    ("risk_mae", "Risk MAE", "lower"),
    ("upper_risk_coverage", "Risk coverage", "higher"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("results/fair_trainval_v2/metrics.json"),
    )
    parser.add_argument(
        "--challengers",
        type=Path,
        nargs="+",
        default=[
            Path("results/fair_trainval_v3_seed2026/metrics.json"),
            Path("results/fair_trainval_v3_seed2027/metrics.json"),
            Path("results/fair_trainval_v3_seed2028/metrics.json"),
        ],
    )
    parser.add_argument(
        "--dataset-metadata",
        type=Path,
        default=Path("data/chronosafe_nuscenes_trainval_timing_v3.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/fair_trainval_aggregate")
    )
    parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--dpi", type=int, default=180)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def log_metrics(
    evaluation: dict[str, object],
    scene_to_log: dict[int, str],
) -> dict[str, dict[str, float]]:
    per_scene = evaluation.get("per_scene")
    if not isinstance(per_scene, dict):
        raise ValueError("Evaluation JSON is missing per_scene metrics")
    accumulators: dict[str, dict[str, float]] = {}
    for scene_text, raw_metrics in per_scene.items():
        scene_id = int(scene_text)
        if scene_id not in scene_to_log:
            raise ValueError(f"No log token for scene {scene_id}")
        if not isinstance(raw_metrics, dict):
            raise ValueError(f"Invalid per-scene metrics for {scene_id}")
        log_token = scene_to_log[scene_id]
        sequences = float(raw_metrics["sequences"])
        target = accumulators.setdefault(
            log_token,
            {"sequences": 0.0, **{name: 0.0 for name, _, _ in METRICS}},
        )
        target["sequences"] += sequences
        for name, _, _ in METRICS:
            target[name] += float(raw_metrics[name]) * sequences
    for values in accumulators.values():
        sequences = values["sequences"]
        for name, _, _ in METRICS:
            values[name] /= sequences
    return accumulators


def percentile_interval(values: np.ndarray) -> tuple[float, float]:
    lower, upper = np.quantile(values, [0.025, 0.975])
    return float(lower), float(upper)


def seed_t_interval(values: np.ndarray) -> tuple[float, float]:
    """95% t interval for the preregistered three training seeds (df=2)."""

    mean = float(values.mean())
    if len(values) < 2:
        return mean, mean
    critical = 4.3026527299 if len(values) == 3 else 1.96
    half_width = critical * float(values.std(ddof=1)) / np.sqrt(len(values))
    return mean - half_width, mean + half_width


def weighted_bootstrap(
    values: np.ndarray,
    weights: np.ndarray,
    sampled_indices: np.ndarray,
) -> np.ndarray:
    sampled_values = values[sampled_indices]
    sampled_weights = weights[sampled_indices]
    return (sampled_values * sampled_weights).sum(axis=1) / sampled_weights.sum(axis=1)


def format_value(name: str, value: float) -> str:
    if name in {
        "scenario_accuracy",
        "camera_accuracy",
        "lidar_accuracy",
        "delay_accuracy",
        "upper_risk_coverage",
    }:
        return f"{value * 100:.4f}%"
    return f"{value:.6f}"


def write_plot(rows: list[dict[str, object]], output: Path, logs: int, dpi: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_name = {str(row["metric"]): row for row in rows}
    accuracy_names = [
        "scenario_accuracy",
        "camera_accuracy",
        "lidar_accuracy",
        "delay_accuracy",
        "upper_risk_coverage",
    ]
    risk_names = ["risk_mae", "conformal_radius"]
    figure, axes = plt.subplots(1, 2, figsize=(13.5, 5.3))
    colors = ("#6B7280", "#E95420")

    def bars(axis, names: list[str], percentage: bool) -> None:
        x = np.arange(len(names), dtype=np.float64)
        width = 0.36
        baseline = np.asarray([float(by_name[name]["baseline"]) for name in names])
        challenger = np.asarray([float(by_name[name]["challenger_mean"]) for name in names])
        if percentage:
            baseline *= 100.0
            challenger *= 100.0
        baseline_ci = np.asarray([by_name[name]["baseline_ci95"] for name in names], dtype=float)
        challenger_ci = np.asarray([by_name[name]["challenger_ci95"] for name in names], dtype=float)
        if percentage:
            baseline_ci *= 100.0
            challenger_ci *= 100.0
        baseline_error = np.vstack((baseline - baseline_ci[:, 0], baseline_ci[:, 1] - baseline))
        challenger_error = np.vstack(
            (challenger - challenger_ci[:, 0], challenger_ci[:, 1] - challenger)
        )
        axis.bar(
            x - width / 2,
            baseline,
            width,
            yerr=baseline_error,
            capsize=3,
            color=colors[0],
            label="Locked v2",
        )
        axis.bar(
            x + width / 2,
            challenger,
            width,
            yerr=challenger_error,
            capsize=3,
            color=colors[1],
            label="v3-large (3 seeds)",
        )
        axis.set_xticks(x, [str(by_name[name]["label"]) for name in names], rotation=24, ha="right")
        axis.grid(axis="y", alpha=0.25)

    bars(axes[0], accuracy_names, True)
    axes[0].set_ylabel("Percent (%)")
    axes[0].set_title("Diagnosis and calibrated coverage")
    minimum_accuracy = min(
        min(float(by_name[name]["baseline"]), float(by_name[name]["challenger_mean"]))
        for name in accuracy_names
    )
    axes[0].set_ylim(bottom=max(0.0, minimum_accuracy * 100.0 - 5.0), top=101.0)
    axes[0].legend(loc="lower right")
    bars(axes[1], risk_names, False)
    axes[1].set_ylabel("Lower is better")
    axes[1].set_title("Risk error and calibration sharpness")
    axes[1].legend(loc="upper right")
    figure.suptitle(
        f"ChronoSafe-Drive fair held-out nuScenes comparison ({logs} test logs; mini logs excluded)"
    )
    figure.tight_layout()
    figure.savefig(output, dpi=dpi, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    args = parse_args()
    if args.bootstrap_resamples < 100:
        raise ValueError("--bootstrap-resamples must be at least 100")
    baseline = load_json(args.baseline)
    challengers = [load_json(path) for path in args.challengers]
    if len(challengers) < 2:
        raise ValueError("At least two challenger seeds are required")
    metadata = load_json(args.dataset_metadata)
    scene_to_log = {
        int(scene["scene_id"]): str(scene["log_token"])
        for scene in metadata["scenes"]  # type: ignore[index]
    }
    baseline_logs = log_metrics(baseline, scene_to_log)
    challenger_logs = [log_metrics(payload, scene_to_log) for payload in challengers]
    log_tokens = sorted(baseline_logs)
    if any(sorted(values) != log_tokens for values in challenger_logs):
        raise ValueError("Baseline and challenger evaluations do not cover identical logs")

    weights = np.asarray([baseline_logs[token]["sequences"] for token in log_tokens])
    rng = np.random.default_rng(args.seed)
    sampled_indices = rng.integers(
        0, len(log_tokens), size=(args.bootstrap_resamples, len(log_tokens))
    )
    rows: list[dict[str, object]] = []
    baseline_overall = baseline["overall"]
    challenger_overall = [payload["overall"] for payload in challengers]
    if not isinstance(baseline_overall, dict) or any(
        not isinstance(values, dict) for values in challenger_overall
    ):
        raise ValueError("Evaluation JSON is missing overall metrics")

    for name, label, direction in METRICS:
        baseline_value = float(baseline_overall[name])
        seed_values = np.asarray(
            [float(values[name]) for values in challenger_overall], dtype=np.float64
        )
        challenger_mean = float(seed_values.mean())
        base_log_values = np.asarray([baseline_logs[token][name] for token in log_tokens])
        challenger_log_values = np.asarray(
            [
                np.mean([values[token][name] for values in challenger_logs])
                for token in log_tokens
            ]
        )
        base_bootstrap = weighted_bootstrap(
            base_log_values, weights, sampled_indices
        )
        challenger_bootstrap = weighted_bootstrap(
            challenger_log_values, weights, sampled_indices
        )
        if direction == "higher":
            effect = (challenger_mean - baseline_value) * 100.0
            effect_unit = "percentage_points"
        else:
            effect = (baseline_value - challenger_mean) / baseline_value * 100.0
            effect_unit = "relative_reduction_percent"
        rows.append(
            {
                "metric": name,
                "label": label,
                "direction": direction,
                "baseline": baseline_value,
                "baseline_ci95": percentile_interval(base_bootstrap),
                "challenger_seeds": seed_values.tolist(),
                "challenger_mean": challenger_mean,
                "challenger_std": float(seed_values.std(ddof=1)),
                "challenger_ci95": percentile_interval(challenger_bootstrap),
                "paired_difference_ci95": percentile_interval(
                    challenger_bootstrap - base_bootstrap
                ),
                "effect": effect,
                "effect_unit": effect_unit,
            }
        )

    baseline_radius = float(baseline["conformal_radius"])
    radius_values = np.asarray(
        [float(payload["conformal_radius"]) for payload in challengers]
    )
    radius_mean = float(radius_values.mean())
    radius_ci = seed_t_interval(radius_values)
    rows.append(
        {
            "metric": "conformal_radius",
            "label": "Conformal radius",
            "direction": "lower",
            "baseline": baseline_radius,
            "baseline_ci95": (baseline_radius, baseline_radius),
            "challenger_seeds": radius_values.tolist(),
            "challenger_mean": radius_mean,
            "challenger_std": float(radius_values.std(ddof=1)),
            "challenger_ci95": radius_ci,
            "paired_difference_ci95": (
                radius_ci[0] - baseline_radius,
                radius_ci[1] - baseline_radius,
            ),
            "effect": (baseline_radius - radius_mean) / baseline_radius * 100.0,
            "effect_unit": "relative_reduction_percent",
        }
    )

    summary = {
        "baseline": str(args.baseline),
        "challengers": [str(path) for path in args.challengers],
        "dataset_metadata": str(args.dataset_metadata),
        "training_seed_count": len(challengers),
        "test_scene_count": int(baseline["test_scene_count"]),
        "test_log_count": len(log_tokens),
        "bootstrap_unit": "nuScenes log_token",
        "bootstrap_resamples": args.bootstrap_resamples,
        "bootstrap_seed": args.seed,
        "rows": rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "aggregate.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    with (args.output / "comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "metric",
                "direction",
                "baseline",
                "baseline_ci95_low",
                "baseline_ci95_high",
                "challenger_mean",
                "challenger_std",
                "challenger_ci95_low",
                "challenger_ci95_high",
                "effect",
                "effect_unit",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["metric"],
                    row["direction"],
                    row["baseline"],
                    *row["baseline_ci95"],  # type: ignore[misc]
                    row["challenger_mean"],
                    row["challenger_std"],
                    *row["challenger_ci95"],  # type: ignore[misc]
                    row["effect"],
                    row["effect_unit"],
                ]
            )
    markdown = [
        "# Fair nuScenes Trainval comparison",
        "",
        f"Evaluation uses {baseline['test_scene_count']} scenes grouped into {len(log_tokens)} independent logs; ",
        "all logs containing nuScenes-mini scenes are excluded. Confidence intervals use 10,000 paired log-cluster bootstrap resamples.",
        "",
        "| Metric | Locked v2 | v3-large mean ± SD | v3 95% CI | Effect |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        name = str(row["metric"])
        baseline_text = format_value(name, float(row["baseline"]))
        mean_text = format_value(name, float(row["challenger_mean"]))
        std_text = format_value(name, float(row["challenger_std"]))
        ci_low, ci_high = row["challenger_ci95"]  # type: ignore[misc]
        ci_text = f"[{format_value(name, ci_low)}, {format_value(name, ci_high)}]"
        unit = "pp" if row["effect_unit"] == "percentage_points" else "% reduction"
        markdown.append(
            f"| {row['label']} | {baseline_text} | {mean_text} ± {std_text} | {ci_text} | {float(row['effect']):.4f} {unit} |"
        )
    (args.output / "comparison.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    write_plot(rows, args.output / "fair_comparison.png", len(log_tokens), args.dpi)

    compact = {
        str(row["metric"]): {
            "baseline": row["baseline"],
            "v3_mean": row["challenger_mean"],
            "v3_std": row["challenger_std"],
            "v3_ci95": row["challenger_ci95"],
            "effect": row["effect"],
            "effect_unit": row["effect_unit"],
        }
        for row in rows
    }
    print(json.dumps({"test_logs": len(log_tokens), "metrics": compact}, indent=2))
    print(f"aggregate: {args.output / 'aggregate.json'}")
    print(f"table: {args.output / 'comparison.md'}")
    print(f"figure: {args.output / 'fair_comparison.png'}")
    print("Fair trainval aggregate: PASS")


if __name__ == "__main__":
    main()
