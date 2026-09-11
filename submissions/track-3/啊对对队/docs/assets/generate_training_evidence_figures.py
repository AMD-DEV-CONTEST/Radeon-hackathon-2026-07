#!/usr/bin/env python3
"""Generate the submission training and ablation figures from raw evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


UPDATE_RE = re.compile(r"loss:(?P<loss>[0-9.]+)\s+grdn:(?P<grad>[0-9.]+)")
COLORS = ["#4D4D4D", "#D55E00", "#56B4E9", "#009E73"]
HATCHES = ["//", "xx", "..", "\\\\"]
MARKERS = ["o", "X", "^", "D"]
LABELS = ["Reference\nexecutor", "Raw VLA", "Safety\nclipped VLA", "Harness-\nLite"]
KEYS = ["expert_executor", "raw_vla", "safety_clipped_vla", "harness_lite"]


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
            "font.size": 8,
            "axes.labelsize": 9,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "legend.fontsize": 7.5,
            "axes.linewidth": 0.8,
            "pdf.fonttype": 42,
            "savefig.facecolor": "white",
        }
    )


def read_log(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw[:1024]:
        return raw.decode("utf-16")
    return raw.decode("utf-8", errors="replace")


def rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    if window < 1 or window > values.size:
        raise ValueError("window must be between 1 and the number of observations")
    kernel = np.ones(window, dtype=float) / window
    trend = np.full(values.shape, np.nan, dtype=float)
    trend[window - 1 :] = np.convolve(values, kernel, mode="valid")
    return trend


def save(fig: plt.Figure, output: Path) -> None:
    fig.savefig(output.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def plot_training(root: Path, output_dir: Path, window: int = 100) -> None:
    path = root / "evidence/training/pash-primitive-smolvla-rocm-2800step-v1.log"
    losses = np.array([float(match.group("loss")) for match in UPDATE_RE.finditer(read_log(path))])
    if losses.size != 2800:
        raise RuntimeError(f"expected 2800 updates, parsed {losses.size}")
    steps = np.arange(1, losses.size + 1)
    fig, axis = plt.subplots(figsize=(7.1, 2.65), constrained_layout=True)
    axis.plot(steps, losses, color="#B8BCC0", linewidth=0.45, alpha=0.5, label="Per update")
    axis.plot(steps, rolling_mean(losses, window), color="#0072B2", linewidth=1.6, label=f"{window}-update mean")
    axis.set(xlabel="Training update", ylabel="Imitation loss", xlim=(1, losses.size), ylim=(0, None))
    axis.grid(axis="y", color="#E3E5E7", linewidth=0.55)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, loc="upper right")
    save(fig, output_dir / "training_loss")


def plot_ablation(root: Path, output_dir: Path) -> None:
    path = root / "evidence/training/pash-primitive-smolvla-2800step-offline-ablation-v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["offline_ablation"]
    values = [rows[key] for key in KEYS]
    passes = np.array([row["envelope_pass_count"] for row in values], dtype=float)
    maes = np.array([row["mean_mae"] for row in values], dtype=float)
    total = len(payload.get("stages", []))
    if total < 1 or np.any(passes > total):
        raise RuntimeError("could not derive a valid offline sample count from the evidence")
    x = np.arange(len(LABELS))

    fig, (pass_axis, error_axis) = plt.subplots(1, 2, figsize=(7.1, 2.8), constrained_layout=True)
    bars = pass_axis.bar(
        x,
        passes / total * 100,
        color=COLORS,
        edgecolor="#303030",
        linewidth=0.45,
        width=0.66,
    )
    for bar, hatch in zip(bars, HATCHES, strict=True):
        bar.set_hatch(hatch)
    pass_axis.set(ylabel="Offline action-envelope pass (%)", ylim=(0, 108), xticks=x, xticklabels=LABELS)
    pass_axis.grid(axis="y", color="#E3E5E7", linewidth=0.55)
    for index, count in enumerate(passes.astype(int)):
        pass_axis.text(
            index,
            count / total * 100 + 2,
            f"{count}/{total}",
            ha="center",
            va="bottom",
            fontsize=7.5,
        )

    for index, (value, color, marker) in enumerate(zip(maes, COLORS, MARKERS, strict=True)):
        error_axis.scatter(
            index,
            value,
            s=42,
            color=color,
            marker=marker,
            edgecolors="black",
            linewidths=0.45,
            zorder=3,
        )
    error_axis.set(
        ylabel="Mean 19-D control discrepancy",
        ylim=(0, 0.0072),
        xticks=x,
        xticklabels=LABELS,
    )
    error_axis.grid(axis="y", color="#E3E5E7", linewidth=0.55)
    error_axis.ticklabel_format(axis="y", style="plain", useOffset=False)
    for index, value in enumerate(maes):
        x_offset = 4 if index == 0 else 0
        alignment = "left" if index == 0 else "center"
        error_axis.annotate(
            f"{value:.5f}",
            (index, value),
            xytext=(x_offset, 8),
            textcoords="offset points",
            ha=alignment,
            fontsize=7,
        )

    for label, axis in zip(("A", "B"), (pass_axis, error_axis), strict=True):
        axis.spines[["top", "right"]].set_visible(False)
        axis.text(-0.15, 1.03, label, transform=axis.transAxes, fontsize=10, fontweight="bold")
        axis.tick_params(axis="x", rotation=0, labelsize=7)
    save(fig, output_dir / "offline_ablation")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    output = args.out or args.repo_root / "docs/assets"
    output.mkdir(parents=True, exist_ok=True)
    configure_style()
    plot_training(args.repo_root, output)
    plot_ablation(args.repo_root, output)


if __name__ == "__main__":
    main()
