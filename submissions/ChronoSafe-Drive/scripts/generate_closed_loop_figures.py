"""Generate publication-ready figures from a ChronoSafe closed-loop run."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np


SCENARIO_ORDER = (
    "clean",
    "progressive_blur",
    "camera_freeze",
    "lidar_dropout",
    "dynamic_delay",
    "freeze_plus_dropout",
    "blur_plus_delay",
)
SCENARIO_LABELS = {
    "clean": "Clean",
    "progressive_blur": "Progressive blur",
    "camera_freeze": "Camera freeze",
    "lidar_dropout": "LiDAR dropout",
    "dynamic_delay": "Dynamic delay",
    "freeze_plus_dropout": "Freeze + dropout",
    "blur_plus_delay": "Blur + delay",
}
SCENARIO_COLORS = {
    "clean": "#DDEFE2",
    "progressive_blur": "#FFF0BF",
    "camera_freeze": "#FFD4C8",
    "lidar_dropout": "#D8E7FF",
    "dynamic_delay": "#E6DCF7",
    "freeze_plus_dropout": "#F5B6B6",
    "blur_plus_delay": "#F4D1A6",
}
MODE_COLORS = {
    "NORMAL": "#2A9D8F",
    "DEGRADED": "#F4A261",
    "MINIMAL_RISK": "#D62828",
}
REQUIRED_COLUMNS = {
    "step",
    "scenario",
    "predicted_scenario",
    "true_risk",
    "predicted_risk",
    "risk_upper",
    "mode",
    "speed_km_h",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Closed-loop CSV file")
    parser.add_argument("--output", type=Path, required=True, help="Figure output directory")
    parser.add_argument("--degraded-threshold", type=float, default=0.45)
    parser.add_argument("--minimal-risk-threshold", type=float, default=0.62)
    parser.add_argument("--dpi", type=int, default=180)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Closed-loop CSV does not exist: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError("Closed-loop CSV is empty")
    return rows


def scenario_spans(scenarios: list[str]) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    start = 0
    for index in range(1, len(scenarios) + 1):
        if index == len(scenarios) or scenarios[index] != scenarios[start]:
            spans.append((start, index - 1, scenarios[start]))
            start = index
    return spans


def add_scenario_background(axis, steps: np.ndarray, scenarios: list[str], *, labels: bool) -> None:
    for start, end, scenario in scenario_spans(scenarios):
        left = float(steps[start]) - 0.5
        right = float(steps[end]) + 0.5
        axis.axvspan(left, right, color=SCENARIO_COLORS.get(scenario, "#EEEEEE"), alpha=0.32, lw=0)
        if labels:
            axis.text(
                (left + right) / 2,
                1.025,
                SCENARIO_LABELS.get(scenario, scenario),
                transform=axis.get_xaxis_transform(),
                ha="center",
                va="bottom",
                fontsize=8,
                rotation=18,
            )


def first_index(values: list[str], target: str) -> int | None:
    try:
        return values.index(target)
    except ValueError:
        return None


def configure_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(
            "matplotlib is required. Install it with: python -m pip install matplotlib"
        ) from exc
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.grid": True,
            "grid.alpha": 0.22,
            "grid.linestyle": "--",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.size": 10,
        }
    )
    return plt


def plot_closed_loop(
    rows: list[dict[str, str]],
    output: Path,
    degraded_threshold: float,
    minimal_risk_threshold: float,
    dpi: int,
) -> None:
    plt = configure_matplotlib()
    steps = np.asarray([int(row["step"]) for row in rows])
    scenarios = [row["scenario"] for row in rows]
    modes = [row["mode"] for row in rows]
    true_risk = np.asarray([float(row["true_risk"]) for row in rows])
    predicted_risk = np.asarray([float(row["predicted_risk"]) for row in rows])
    risk_upper = np.asarray([float(row["risk_upper"]) for row in rows])
    speed = np.asarray([float(row["speed_km_h"]) for row in rows])

    figure, (risk_axis, speed_axis) = plt.subplots(
        2,
        1,
        figsize=(15.5, 8.5),
        sharex=True,
        gridspec_kw={"height_ratios": (1.65, 1.0), "hspace": 0.13},
    )
    add_scenario_background(risk_axis, steps, scenarios, labels=True)
    add_scenario_background(speed_axis, steps, scenarios, labels=False)

    risk_axis.plot(steps, true_risk, color="#111827", lw=1.8, label="Ground-truth risk")
    risk_axis.plot(steps, predicted_risk, color="#277DA1", lw=1.5, label="Predicted risk")
    risk_axis.plot(steps, risk_upper, color="#D62828", lw=2.0, label="Calibrated upper risk")
    risk_axis.axhline(
        degraded_threshold,
        color=MODE_COLORS["DEGRADED"],
        lw=1.4,
        ls="--",
        label=f"Degraded threshold ({degraded_threshold:.2f})",
    )
    risk_axis.axhline(
        minimal_risk_threshold,
        color=MODE_COLORS["MINIMAL_RISK"],
        lw=1.4,
        ls="--",
        label=f"MRM threshold ({minimal_risk_threshold:.2f})",
    )
    risk_axis.set_ylim(-0.03, 1.03)
    risk_axis.set_ylabel("Risk")
    risk_axis.set_title("ChronoSafe-Drive: Calibrated Risk and Closed-Loop Minimal-Risk Maneuver", pad=34)
    risk_axis.legend(loc="upper left", ncol=3, frameon=True, fontsize=9)

    for start, end, mode in scenario_spans(modes):
        speed_axis.axvspan(
            float(steps[start]) - 0.5,
            float(steps[end]) + 0.5,
            color=MODE_COLORS.get(mode, "#BBBBBB"),
            alpha=0.13,
            lw=0,
        )
    speed_axis.plot(steps, speed, color="#264653", lw=2.2, label="Vehicle speed")
    mrm_index = first_index(modes, "MINIMAL_RISK")
    if mrm_index is not None:
        mrm_step = int(steps[mrm_index])
        for axis in (risk_axis, speed_axis):
            axis.axvline(mrm_step, color=MODE_COLORS["MINIMAL_RISK"], lw=1.5, ls=":")
        speed_axis.annotate(
            f"MRM triggered at step {mrm_step}",
            xy=(mrm_step, speed[mrm_index]),
            xytext=(-110, 28),
            textcoords="offset points",
            arrowprops={"arrowstyle": "->", "color": MODE_COLORS["MINIMAL_RISK"]},
            color=MODE_COLORS["MINIMAL_RISK"],
            fontweight="bold",
        )
    speed_axis.set_ylabel("Speed (km/h)")
    speed_axis.set_xlabel("Simulation step")
    speed_axis.set_ylim(bottom=-0.8)
    speed_axis.legend(loc="upper left")
    figure.savefig(output / "closed_loop_timeline.png", dpi=dpi, bbox_inches="tight")
    plt.close(figure)


def plot_diagnosis(rows: list[dict[str, str]], output: Path, dpi: int) -> None:
    plt = configure_matplotlib()
    steps = np.asarray([int(row["step"]) for row in rows])
    truth = [row["scenario"] for row in rows]
    prediction = [row["predicted_scenario"] for row in rows]
    labels = [scenario for scenario in SCENARIO_ORDER if scenario in set(truth + prediction)]
    labels.extend(sorted(set(truth + prediction).difference(labels)))
    mapping = {label: index for index, label in enumerate(labels)}
    image_data = np.asarray(
        [[mapping[value] for value in truth], [mapping[value] for value in prediction]], dtype=np.int64
    )
    colors = [SCENARIO_COLORS.get(label, "#AAAAAA") for label in labels]
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    figure, axis = plt.subplots(figsize=(15.5, 3.4))
    axis.imshow(
        image_data,
        aspect="auto",
        interpolation="nearest",
        cmap=ListedColormap(colors),
        vmin=-0.5,
        vmax=len(labels) - 0.5,
        extent=(float(steps[0]) - 0.5, float(steps[-1]) + 0.5, 1.5, -0.5),
    )
    axis.grid(False)
    axis.set_yticks((0, 1), labels=("Ground truth", "Prediction"))
    axis.set_xlabel("Simulation step")
    axis.set_title("Compositional Multi-Sensor Degradation Diagnosis")
    axis.legend(
        handles=[Patch(facecolor=colors[index], label=SCENARIO_LABELS.get(label, label)) for index, label in enumerate(labels)],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.34),
        ncol=min(7, len(labels)),
        frameon=False,
        fontsize=9,
    )
    figure.savefig(output / "diagnosis_timeline.png", dpi=dpi, bbox_inches="tight")
    plt.close(figure)


def plot_confusion_matrix(rows: list[dict[str, str]], output: Path, dpi: int) -> None:
    plt = configure_matplotlib()
    truth = [row["scenario"] for row in rows]
    prediction = [row["predicted_scenario"] for row in rows]
    labels = [scenario for scenario in SCENARIO_ORDER if scenario in set(truth + prediction)]
    labels.extend(sorted(set(truth + prediction).difference(labels)))
    mapping = {label: index for index, label in enumerate(labels)}
    matrix = np.zeros((len(labels), len(labels)), dtype=np.int64)
    for true_label, predicted_label in zip(truth, prediction, strict=True):
        matrix[mapping[true_label], mapping[predicted_label]] += 1
    row_totals = np.maximum(matrix.sum(axis=1, keepdims=True), 1)
    normalized = matrix / row_totals

    figure, axis = plt.subplots(figsize=(9.2, 7.8))
    image = axis.imshow(normalized, cmap="Blues", vmin=0.0, vmax=1.0)
    display_labels = [SCENARIO_LABELS.get(label, label) for label in labels]
    axis.set_xticks(range(len(labels)), labels=display_labels, rotation=35, ha="right")
    axis.set_yticks(range(len(labels)), labels=display_labels)
    axis.set_xlabel("Predicted scenario")
    axis.set_ylabel("Ground-truth scenario")
    axis.set_title("Scenario Diagnosis Confusion Matrix")
    axis.grid(False)
    for row_index in range(len(labels)):
        for column_index in range(len(labels)):
            value = normalized[row_index, column_index]
            axis.text(
                column_index,
                row_index,
                f"{matrix[row_index, column_index]}\n{value:.0%}",
                ha="center",
                va="center",
                color="white" if value > 0.52 else "#111827",
                fontsize=8,
            )
    figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04, label="Row-normalized rate")
    figure.savefig(output / "scenario_confusion_matrix.png", dpi=dpi, bbox_inches="tight")
    plt.close(figure)


def write_summary(
    rows: list[dict[str, str]],
    input_path: Path,
    output: Path,
    degraded_threshold: float,
    minimal_risk_threshold: float,
) -> dict[str, object]:
    truth = [row["scenario"] for row in rows]
    prediction = [row["predicted_scenario"] for row in rows]
    true_risk = np.asarray([float(row["true_risk"]) for row in rows])
    predicted_risk = np.asarray([float(row["predicted_risk"]) for row in rows])
    risk_upper = np.asarray([float(row["risk_upper"]) for row in rows])
    modes = [row["mode"] for row in rows]
    mrm_index = first_index(modes, "MINIMAL_RISK")
    summary: dict[str, object] = {
        "source_csv": str(input_path),
        "steps": len(rows),
        "scenario_accuracy": round(float(np.mean(np.asarray(truth) == np.asarray(prediction))), 6),
        "risk_mae": round(float(np.mean(np.abs(true_risk - predicted_risk))), 6),
        "upper_risk_coverage": round(float(np.mean(true_risk <= risk_upper)), 6),
        "degraded_threshold": degraded_threshold,
        "minimal_risk_threshold": minimal_risk_threshold,
        "mode_counts": dict(Counter(modes)),
        "minimal_risk_reached": mrm_index is not None,
        "minimal_risk_step": None if mrm_index is None else int(rows[mrm_index]["step"]),
        "final_speed_km_h": float(rows[-1]["speed_km_h"]),
    }
    (output / "figure_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    if not 0.0 <= args.degraded_threshold < args.minimal_risk_threshold <= 1.0:
        raise ValueError("Thresholds must satisfy 0 <= degraded < minimal-risk <= 1")
    rows = load_rows(args.input)
    args.output.mkdir(parents=True, exist_ok=True)
    plot_closed_loop(
        rows,
        args.output,
        args.degraded_threshold,
        args.minimal_risk_threshold,
        args.dpi,
    )
    plot_diagnosis(rows, args.output, args.dpi)
    plot_confusion_matrix(rows, args.output, args.dpi)
    summary = write_summary(
        rows,
        args.input,
        args.output,
        args.degraded_threshold,
        args.minimal_risk_threshold,
    )
    print(json.dumps(summary, indent=2))
    print(f"figures: {args.output}")
    print("ChronoSafe figure generation: PASS")


if __name__ == "__main__":
    main()
