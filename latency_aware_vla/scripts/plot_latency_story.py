#!/usr/bin/env python3
"""Conference figure: freeze vs continuous motion under +200 ms delay."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


def main():
    root = Path(__file__).resolve().parents[1]
    runs = [
        ("Sync-full\n+200 ms", root / "output/eval/smolvla_sync_E50_d200_n20_s400/eval_summary.json", "#0072B2"),
        ("Async\n+200 ms", root / "output/eval/smolvla_async_E10_d200_n20/eval_summary.json", "#CC79A7"),
        ("RTC\n+200 ms", root / "output/eval/smolvla_rtc_E10_d200_n20/eval_summary.json", "#009E73"),
        ("Sync-full\nnative", root / "output/eval/smolvla_sync_E50_n20_s400/eval_summary.json", "#56B4E9"),
    ]
    labels, place, lift, colors = [], [], [], []
    for lab, path, c in runs:
        s = json.loads(path.read_text())
        labels.append(lab)
        place.append(s["success_rate"])
        lift.append(s.get("lift_rate", s.get("n_lifted", 0) / s["n_episodes"]))
        colors.append(c)

    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["DejaVu Serif", "Times New Roman", "Times", "serif"],
            "axes.spines.top": False,
            "axes.spines.right": False,
            "savefig.dpi": 300,
            "pdf.fonttype": 42,
        }
    )
    x = np.arange(len(labels))
    w = 0.36
    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    ax.bar(x - w / 2, place, w, label="Place success", color=colors, edgecolor="black", linewidth=0.5)
    ax.bar(x + w / 2, lift, w, label="Lift success", color=colors, alpha=0.45, edgecolor="black", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 0.35)
    ax.set_ylabel("Rate")
    ax.yaxis.set_major_formatter(mpl.ticker.PercentFormatter(1.0))
    ax.set_title("SmolVLA under latency: Sync freeze vs continuous queue")
    ax.legend(frameon=False, loc="upper right")
    # annotate freeze
    ax.text(0, 0.28, "freezes", ha="center", fontsize=8, color="#666")
    ax.text(1, 0.28, "freeze=0", ha="center", fontsize=8, color="#666")
    ax.text(2, 0.28, "freeze=0", ha="center", fontsize=8, color="#666")
    fig.tight_layout()
    out = root / "artifacts/figures/eval/env_a_latency_story"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
    print(f"[plot] {out.with_suffix('.png')}")


if __name__ == "__main__":
    main()
