#!/usr/bin/env python3
"""Conference-style plots for Sync closed-loop eval summaries.

Figures:
  - success_bars: success / lift / place with Wilson 95% CI
  - paired_success: per-episode success heatmap across conditions (same seed)
  - latency_vram: inference latency + peak VRAM dual panel
  - lift_dist: max lift height distribution
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = (z / den) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def apply_conference_style() -> None:
    mpl.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "font.family": "serif",
            "font.serif": ["DejaVu Serif", "Times New Roman", "Times", "serif"],
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 12,
            "legend.fontsize": 9,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.linewidth": 0.4,
            "grid.alpha": 0.35,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


# Colorblind-friendly discrete palette (not purple-default)
COLORS = {
    "smolvla": "#0072B2",
    "pi05": "#D55E00",
    "rtc": "#009E73",
    "async": "#CC79A7",
}


def _label(s: dict) -> str:
    pol = s.get("policy", "?")
    delay = s.get("delay_ms", 0) or 0
    mode = s.get("mode", "sync")
    e = s.get("action_horizon_E")
    name = {"smolvla": "SmolVLA", "pi05": "π0.5"}.get(pol, pol)
    mode_l = {"sync": "Sync", "rtc": "RTC", "async": "Async"}.get(mode, mode)
    extra = f" E={e}" if e is not None else ""
    if delay and delay > 0:
        return f"{name} {mode_l}{extra}\n+{int(delay)} ms"
    return f"{name} {mode_l}{extra}"


def _color(s: dict) -> str:
    mode = s.get("mode", "")
    if mode == "rtc":
        return COLORS["rtc"]
    if mode == "async":
        return COLORS["async"]
    return COLORS.get(s.get("policy", ""), "#333333")


def plot_success_bars(summaries: list[dict], out: Path) -> None:
    apply_conference_style()
    labels = [_label(s) for s in summaries]
    metrics = [
        ("success_rate", "n_success", "Place success"),
        ("lift_rate", "n_lifted", "Lift success"),
        ("place_rate", "n_placed", "In-basket"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4), sharey=True)
    x = np.arange(len(summaries))
    width = 0.65

    for ax, (rate_key, count_key, title) in zip(axes, metrics):
        rates, yerr_lo, yerr_hi, colors = [], [], [], []
        for s in summaries:
            n = int(s.get("n_episodes", 0))
            if count_key in s:
                k = int(s[count_key])
            elif rate_key == "success_rate":
                k = int(s.get("n_success", 0))
            else:
                # fallback from per-ep results
                results = s.get("results", [])
                if rate_key == "lift_rate":
                    k = sum(1 for r in results if r.get("lifted_ok"))
                else:
                    k = sum(1 for r in results if r.get("placed_ok"))
            rate = k / n if n else 0.0
            lo, hi = wilson_ci(k, n)
            rates.append(rate)
            yerr_lo.append(rate - lo)
            yerr_hi.append(hi - rate)
            colors.append(_color(s))
        ax.bar(x, rates, width, color=colors, edgecolor="black", linewidth=0.5, zorder=3)
        ax.errorbar(
            x, rates, yerr=[yerr_lo, yerr_hi], fmt="none", ecolor="black",
            elinewidth=1.0, capsize=3, zorder=4,
        )
        for i, (r, s) in enumerate(zip(rates, summaries)):
            n = int(s.get("n_episodes", 0))
            k = int(round(r * n))
            ax.text(i, min(r + 0.04, 1.02), f"{k}/{n}", ha="center", va="bottom", fontsize=8)
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_ylim(0, 1.15)
        ax.set_ylabel("Rate" if ax is axes[0] else "")
        ax.yaxis.set_major_formatter(mpl.ticker.PercentFormatter(1.0))

    fig.suptitle("Env-A closed-loop Sync evaluation (Wilson 95% CI)", y=1.02, fontsize=12)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] wrote {out.with_suffix('.png')}")


def plot_latency_vram(summaries: list[dict], out: Path) -> None:
    apply_conference_style()
    labels = [_label(s) for s in summaries]
    x = np.arange(len(summaries))
    p50 = [s.get("infer_latency_ms", {}).get("p50") or 0 for s in summaries]
    p95 = [s.get("infer_latency_ms", {}).get("p95") or 0 for s in summaries]
    vram = [s.get("peak_vram_gb") or 0 for s in summaries]
    colors = [_color(s) for s in summaries]

    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(8.8, 3.3))
    ax0.bar(x - 0.18, p50, 0.36, label="P50", color=colors, edgecolor="black", linewidth=0.5)
    ax0.bar(x + 0.18, p95, 0.36, label="P95", color=colors, alpha=0.45, edgecolor="black", linewidth=0.5)
    ax0.set_xticks(x)
    ax0.set_xticklabels(labels, fontsize=8)
    ax0.set_ylabel("Inference latency (ms)")
    ax0.set_title("Replan inference latency")
    ax0.legend(frameon=False, loc="upper left")

    ax1.bar(x, vram, 0.65, color=colors, edgecolor="black", linewidth=0.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=8)
    ax1.set_ylabel("Peak VRAM (GB)")
    ax1.set_title("Peak GPU memory")
    for i, v in enumerate(vram):
        ax1.text(i, v + 0.05, f"{v:.2f}", ha="center", va="bottom", fontsize=8)

    fig.suptitle("AMD Radeon · ROCm resource profile", y=1.02, fontsize=12)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] wrote {out.with_suffix('.png')}")


def plot_paired_heatmap(summaries: list[dict], out: Path) -> None:
    """Per-episode success matrix for paired seed comparison."""
    apply_conference_style()
    if not summaries:
        return
    n = max(len(s.get("results", [])) for s in summaries)
    if n == 0:
        return
    mat = np.zeros((len(summaries), n))
    for i, s in enumerate(summaries):
        for r in s.get("results", []):
            mat[i, int(r["episode"])] = 1.0 if r.get("success") else 0.0

    fig, ax = plt.subplots(figsize=(max(6.5, n * 0.28), 1.4 + 0.45 * len(summaries)))
    im = ax.imshow(mat, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1, interpolation="nearest")
    ax.set_yticks(range(len(summaries)))
    ax.set_yticklabels([_label(s).replace("\n", " ") for s in summaries], fontsize=9)
    ax.set_xlabel("Episode index (shared seed)")
    ax.set_title("Paired episode outcomes (green = success)")
    cbar = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.02, ticks=[0, 1])
    cbar.ax.set_yticklabels(["fail", "ok"])
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] wrote {out.with_suffix('.png')}")


def plot_lift_dist(summaries: list[dict], out: Path) -> None:
    apply_conference_style()
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    data, labels, colors = [], [], []
    for s in summaries:
        lifts = [r.get("max_lift_m", 0) for r in s.get("results", [])]
        if not lifts:
            continue
        data.append(lifts)
        labels.append(_label(s).replace("\n", " "))
        colors.append(_color(s))
    if not data:
        return
    parts = ax.violinplot(data, showmeans=True, showmedians=True)
    for i, body in enumerate(parts["bodies"]):
        body.set_facecolor(colors[i])
        body.set_alpha(0.55)
    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Max lift height (m)")
    ax.set_title("Lift height distribution")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] wrote {out.with_suffix('.png')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summaries", nargs="+", required=True, help="eval_summary.json paths")
    ap.add_argument("--out-dir", default="artifacts/figures/eval")
    ap.add_argument("--tag", default="env_a_sync")
    args = ap.parse_args()

    summaries = []
    for p in args.summaries:
        path = Path(p)
        summaries.append(json.loads(path.read_text()))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = args.tag
    plot_success_bars(summaries, out_dir / f"{tag}_success")
    plot_latency_vram(summaries, out_dir / f"{tag}_latency_vram")
    plot_paired_heatmap(summaries, out_dir / f"{tag}_paired")
    plot_lift_dist(summaries, out_dir / f"{tag}_lift")
    print(f"[plot] done → {out_dir}")


if __name__ == "__main__":
    main()
