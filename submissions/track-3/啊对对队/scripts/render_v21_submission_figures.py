#!/usr/bin/env python3
"""Render video-ready scientific figures from frozen v21 evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np


BLUE = "#0072B2"
SKY = "#56B4E9"
GREEN = "#009E73"
ORANGE = "#E69F00"
VERMILLION = "#D55E00"
GRAY = "#7A7A7A"
LIGHT = "#ECEFF1"


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.labelsize": 10,
            "axes.titlesize": 10,
            "axes.linewidth": 0.8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig: plt.Figure, output: Path, name: str) -> None:
    fig.savefig(output / f"{name}.png", dpi=300, bbox_inches="tight")
    fig.savefig(output / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def add_box(
    ax: plt.Axes,
    xy: tuple[float, float],
    width: float,
    height: float,
    text: str,
    color: str,
    fontsize: float = 6.6,
) -> None:
    patch = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle="round,pad=0.012,rounding_size=0.02",
        facecolor="white",
        edgecolor=color,
        linewidth=1.6,
    )
    ax.add_patch(patch)
    ax.text(
        xy[0] + width / 2,
        xy[1] + height / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        color="black",
    )


def add_arrow(
    ax: plt.Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    color: str = "black",
    linestyle: str = "-",
) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=11,
            linewidth=1.1,
            color=color,
            linestyle=linestyle,
        )
    )


def render_architecture(output: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.1, 3.994))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    xs = [0.03, 0.20, 0.37, 0.54, 0.71, 0.88]
    labels = [
        "Observation\nRGB-D + state",
        "Responses\nAgent\nplan + recovery",
        "Authority\ngate\nstrict schema",
        "v21 PI0.5\n3-vote\nmode route",
        "Motion\ncontroller",
        "Genesis\nsafety gates",
    ]
    colors = [GRAY, BLUE, VERMILLION, GREEN, ORANGE, BLACK if False else GRAY]
    widths = [0.12, 0.12, 0.12, 0.12, 0.12, 0.09]
    for x, label, color, width in zip(xs, labels, colors, widths):
        add_box(ax, (x, 0.53), width, 0.22, label, color)
    for idx in range(len(xs) - 1):
        add_arrow(
            ax,
            (xs[idx] + widths[idx], 0.64),
            (xs[idx + 1] - 0.008, 0.64),
        )
    add_box(ax, (0.54, 0.16), 0.12, 0.17, "VLA action head\nshadow only", SKY)
    add_arrow(ax, (0.60, 0.53), (0.60, 0.34), SKY, "--")
    ax.text(0.03, 0.90, "Agent-conditioned, VLA-routed hybrid", fontsize=13, weight="bold")
    ax.text(
        0.03,
        0.84,
        "Learned routing is real; continuous robot motion remains deterministic.",
        fontsize=9,
        color="#333333",
    )
    ax.text(
        0.205,
        0.42,
        "Agent is rejected if it emits poses, joint targets, tool commands,\n"
        "safety overrides, or checkpoint changes.",
        fontsize=7.2,
        color=VERMILLION,
        ha="left",
    )
    save_figure(fig, output, "01_system_architecture")


def render_success_results(data: dict, output: Path) -> None:
    episodes = data["episodes"]
    labels = [item["label"] for item in episodes]
    x = np.arange(len(labels))
    distances = [item["transport_distance_m"] for item in episodes]
    errors = [item["placement_error_mm"] for item in episodes]
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.994), constrained_layout=True)
    axes[0].plot(x, distances, "o-", color=BLUE, linewidth=1.5, markersize=7)
    axes[0].set_ylabel("Transport distance (m)")
    axes[0].set_xticks(x, labels)
    axes[0].set_ylim(0, 0.62)
    axes[0].grid(axis="y", color="#D9D9D9", linewidth=0.6)
    axes[0].spines[["top", "right"]].set_visible(False)
    axes[0].text(-0.12, 1.03, "a", transform=axes[0].transAxes, weight="bold", fontsize=11)
    for index, value in enumerate(distances):
        axes[0].text(index, value + 0.025, f"{value:.3f}", ha="center", fontsize=8)

    axes[1].bar(x, errors, color=[SKY, GREEN, ORANGE], width=0.58)
    axes[1].set_ylabel("Placement error (mm)")
    axes[1].set_xticks(x, labels)
    axes[1].set_ylim(0, 30)
    axes[1].grid(axis="y", color="#D9D9D9", linewidth=0.6)
    axes[1].spines[["top", "right"]].set_visible(False)
    axes[1].text(-0.12, 1.03, "b", transform=axes[1].transAxes, weight="bold", fontsize=11)
    for index, value in enumerate(errors):
        axes[1].text(index, value + 1.0, f"{value:.1f}", ha="center", fontsize=8)
        axes[1].text(index, 1.2, "side 3/3", ha="center", fontsize=7, color="#333333")
    save_figure(fig, output, "02_success_results")


def render_attribution(data: dict, output: Path) -> None:
    rows = data["development_results"]
    labels = [item["label"] for item in rows]
    success = np.asarray([item["successes"] for item in rows])
    failure = np.asarray([item["attempts"] - item["successes"] for item in rows])
    y = np.arange(len(rows))
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.994), constrained_layout=True)
    axes[0].barh(y, success, color=BLUE, label="Complete task")
    axes[0].barh(y, failure, left=success, color=LIGHT, edgecolor=GRAY, label="Not complete")
    axes[0].set_yticks(y, labels)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Recorded trials (different protocols)")
    axes[0].set_xlim(0, 10.5)
    axes[0].spines[["top", "right"]].set_visible(False)
    axes[0].grid(axis="x", color="#D9D9D9", linewidth=0.6)
    axes[0].legend(frameon=False, loc="lower right")
    axes[0].text(-0.12, 1.03, "a", transform=axes[0].transAxes, weight="bold", fontsize=11)
    for index, item in enumerate(rows):
        axes[0].text(item["attempts"] + 0.2, index, f"{item['successes']}/{item['attempts']}", va="center", fontsize=8)

    ownership = np.asarray(
        [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ]
    )
    axes[1].imshow(ownership, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    axes[1].set_xticks(
        np.arange(4),
        ["Task\nconditioning", "Grasp\nroute", "Continuous\nmotion", "Safety\ngates"],
    )
    axes[1].set_yticks(np.arange(4), ["Agent", "v21 PI0.5", "Scripted controller", "Safety layer"])
    for row in range(4):
        for col in range(4):
            axes[1].text(col, row, "owns" if ownership[row, col] else "-", ha="center", va="center", color="white" if ownership[row, col] else GRAY, fontsize=8)
    axes[1].tick_params(length=0)
    axes[1].text(-0.12, 1.03, "b", transform=axes[1].transAxes, weight="bold", fontsize=11)
    save_figure(fig, output, "03_attribution_comparison")


def render_end_card(output: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.1, 3.994))
    ax.axis("off")
    ax.plot([0.08, 0.92], [0.79, 0.79], color=BLUE, linewidth=3, transform=ax.transAxes)
    ax.text(0.08, 0.66, "Parcel Sorter ROCm", transform=ax.transAxes, fontsize=22, weight="bold")
    ax.text(0.08, 0.54, "Agent-conditioned · v21 VLA-routed · scripted motion", transform=ax.transAxes, fontsize=11, color="#333333")
    ax.text(0.08, 0.36, "Code", transform=ax.transAxes, fontsize=9, color=GRAY)
    ax.text(0.20, 0.36, "github.com/2658183739/Radeon-hackathon-2026-07", transform=ax.transAxes, fontsize=10, color=BLUE)
    ax.text(0.08, 0.25, "Model", transform=ax.transAxes, fontsize=9, color=GRAY)
    ax.text(0.20, 0.25, "huggingface.co/L2658183739/agengt-vla", transform=ax.transAxes, fontsize=10, color=BLUE)
    ax.text(0.08, 0.10, "AMD Radeon · ROCm 7.2.1 · Genesis 1.2.3", transform=ax.transAxes, fontsize=8.5, color="#333333")
    save_figure(fig, output, "04_end_card")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = json.loads(args.data.read_text(encoding="utf-8"))
    configure_style()
    render_architecture(args.output)
    render_success_results(data, args.output)
    render_attribution(data, args.output)
    render_end_card(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
