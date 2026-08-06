#!/usr/bin/env python3
"""Plot LeRobot / SmolVLA train_metrics.json in a clean conference style.

Example:
  python scripts/plot_train_curves.py \\
    --metrics output/train/smolvla_fruit_place_b0/train_metrics.json \\
    --summary output/train/smolvla_fruit_place_b0/train_summary.json \\
    --out artifacts/figures/smolvla_fruit_place_b0
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


def ema(xs: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    if len(xs) == 0:
        return xs
    out = np.empty_like(xs, dtype=float)
    out[0] = xs[0]
    for i in range(1, len(xs)):
        out[i] = alpha * xs[i] + (1.0 - alpha) * out[i - 1]
    return out


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
            "legend.fontsize": 10,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.linewidth": 0.4,
            "grid.alpha": 0.35,
            "lines.linewidth": 1.6,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def load_metrics(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError(f"Expected a list of step records in {path}")
    return data


def plot_curves(
    metrics: list[dict],
    out_prefix: Path,
    summary: dict | None = None,
    title: str | None = None,
    ema_alpha: float = 0.05,
) -> dict:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    steps = np.array([m["step"] for m in metrics], dtype=float)
    loss = np.array([m["loss"] for m in metrics], dtype=float)
    grad = np.array([m.get("grad_norm", np.nan) for m in metrics], dtype=float)
    step_t = np.array([m.get("step_time_s", np.nan) for m in metrics], dtype=float)
    loss_s = ema(loss, ema_alpha)

    apply_conference_style()

    # ---- Figure 1: loss ----
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    ax.plot(steps, loss, color="#9aa5b1", alpha=0.35, linewidth=0.9, label="raw")
    ax.plot(steps, loss_s, color="#1f4e79", linewidth=2.0, label=f"EMA ({ema_alpha:g})")
    ax.set_xlabel("Training step")
    ax.set_ylabel("Loss")
    if title:
        ax.set_title(title)
    ax.legend(frameon=False, loc="upper right")
    if summary:
        txt = []
        if summary.get("final_loss") is not None:
            txt.append(f"final={summary['final_loss']:.4f}")
        if summary.get("total_time_s") is not None:
            txt.append(f"time={summary['total_time_s']/60:.1f} min")
        if summary.get("peak_vram_mb") is not None:
            txt.append(f"peak VRAM={summary['peak_vram_mb']/1024:.1f} GB")
        if txt:
            ax.text(
                0.02,
                0.02,
                "  ·  ".join(txt),
                transform=ax.transAxes,
                va="bottom",
                ha="left",
                fontsize=8,
                color="#334155",
            )
    fig.tight_layout()
    loss_png = out_prefix.with_name(out_prefix.name + "_loss.png")
    loss_pdf = out_prefix.with_name(out_prefix.name + "_loss.pdf")
    fig.savefig(loss_png, bbox_inches="tight")
    fig.savefig(loss_pdf, bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 2: 2-panel loss + grad ----
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.3))
    axes[0].plot(steps, loss, color="#9aa5b1", alpha=0.35, linewidth=0.9)
    axes[0].plot(steps, loss_s, color="#1f4e79", linewidth=2.0)
    axes[0].set_xlabel("Training step")
    axes[0].set_ylabel("Loss")
    axes[0].set_title("(a) Training loss")

    axes[1].plot(steps, grad, color="#b45309", alpha=0.45, linewidth=0.9, label="raw")
    axes[1].plot(steps, ema(grad, ema_alpha), color="#7c2d12", linewidth=2.0, label="EMA")
    axes[1].set_xlabel("Training step")
    axes[1].set_ylabel("Gradient norm")
    axes[1].set_title("(b) Gradient norm")
    axes[1].legend(frameon=False, loc="upper right")
    fig.tight_layout()
    panel_png = out_prefix.with_name(out_prefix.name + "_loss_grad.png")
    panel_pdf = out_prefix.with_name(out_prefix.name + "_loss_grad.pdf")
    fig.savefig(panel_png, bbox_inches="tight")
    fig.savefig(panel_pdf, bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 3: throughput helper ----
    if np.isfinite(step_t).any():
        fig, ax = plt.subplots(figsize=(5.2, 3.0))
        ax.plot(steps, step_t, color="#0f766e", alpha=0.5, linewidth=0.9)
        ax.plot(steps, ema(step_t, 0.1), color="#115e59", linewidth=2.0)
        ax.set_xlabel("Training step")
        ax.set_ylabel("Step time (s)")
        ax.set_title("Per-step wall time")
        fig.tight_layout()
        time_png = out_prefix.with_name(out_prefix.name + "_steptime.png")
        fig.savefig(time_png, bbox_inches="tight")
        fig.savefig(out_prefix.with_name(out_prefix.name + "_steptime.pdf"), bbox_inches="tight")
        plt.close(fig)
    else:
        time_png = None

    meta = {
        "n_records": len(metrics),
        "loss_start": float(loss[0]) if len(loss) else None,
        "loss_end": float(loss[-1]) if len(loss) else None,
        "loss_ema_end": float(loss_s[-1]) if len(loss_s) else None,
        "mean_step_time_s": float(np.nanmean(step_t)) if len(step_t) else None,
        "outputs": {
            "loss_png": str(loss_png),
            "loss_pdf": str(loss_pdf),
            "loss_grad_png": str(panel_png),
            "loss_grad_pdf": str(panel_pdf),
            "steptime_png": str(time_png) if time_png else None,
        },
    }
    meta_path = out_prefix.with_name(out_prefix.name + "_plot_meta.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Conference-style train curve plots")
    ap.add_argument("--metrics", type=str, required=True)
    ap.add_argument("--summary", type=str, default=None)
    ap.add_argument("--out", type=str, required=True, help="Output prefix (no extension)")
    ap.add_argument("--title", type=str, default=None)
    ap.add_argument("--ema-alpha", type=float, default=0.05)
    args = ap.parse_args()

    metrics = load_metrics(Path(args.metrics))
    summary = None
    if args.summary:
        summary = json.loads(Path(args.summary).read_text())
    title = args.title
    if title is None and summary is not None:
        title = f"{summary.get('dataset_id', 'train')} · {summary.get('n_steps', '?')} steps"

    meta = plot_curves(
        metrics,
        Path(args.out),
        summary=summary,
        title=title,
        ema_alpha=args.ema_alpha,
    )
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
