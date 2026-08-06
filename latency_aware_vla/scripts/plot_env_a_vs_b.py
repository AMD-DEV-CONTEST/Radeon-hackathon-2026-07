#!/usr/bin/env python3
"""Conference figure: Env-A (train dist) vs Env-B (held-out 3–5 cm shift)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


def wilson(k, n, z=1.96):
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = (z / den) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, c - h), min(1.0, c + h)


def load(p):
    return json.loads(Path(p).read_text())


def main():
    root = Path(__file__).resolve().parents[1]
    pairs = [
        (
            "SmolVLA",
            root / "output/eval/smolvla_sync_E50_n20_s400/eval_summary.json",
            root / "output/eval/smolvla_sync_E50_envb_n20/eval_summary.json",
            "#0072B2",
        ),
        (
            "π0.5 B1d",
            root / "output/eval/pi05_sync_E50_b1d_n20/eval_summary.json",
            root / "output/eval/pi05_sync_E50_b1d_envb_n20/eval_summary.json",
            "#D55E00",
        ),
    ]
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
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 3.5), sharey=True)
    x = np.arange(len(pairs))
    w = 0.36

    for ax, metric, title in [
        (axes[0], "success_rate", "Place success"),
        (axes[1], "lift_rate", "Lift success"),
    ]:
        a_rates, b_rates, a_err, b_err, colors = [], [], [[], []], [[], []], []
        for name, pa, pb, col in pairs:
            if not pa.exists() or not pb.exists():
                print(f"[plot] missing {pa.name if not pa.exists() else pb.name}; skip")
                return
            sa, sb = load(pa), load(pb)
            colors.append(col)
            for s, rates, err, key_n in [
                (sa, a_rates, a_err, "n_success" if metric == "success_rate" else "n_lifted"),
                (sb, b_rates, b_err, "n_success" if metric == "success_rate" else "n_lifted"),
            ]:
                n = s["n_episodes"]
                k = int(s.get(key_n, round(s[metric] * n)))
                r = k / n
                lo, hi = wilson(k, n)
                rates.append(r)
                err[0].append(r - lo)
                err[1].append(hi - r)
        ax.bar(x - w / 2, a_rates, w, label="Env-A (train dist.)", color=colors, edgecolor="k", lw=0.5)
        ax.bar(
            x + w / 2,
            b_rates,
            w,
            label="Env-B (+3–5 cm shift)",
            color=colors,
            alpha=0.45,
            edgecolor="k",
            lw=0.5,
        )
        ax.errorbar(x - w / 2, a_rates, yerr=a_err, fmt="none", ecolor="k", capsize=3)
        ax.errorbar(x + w / 2, b_rates, yerr=b_err, fmt="none", ecolor="k", capsize=3)
        ax.set_xticks(x)
        ax.set_xticklabels([p[0] for p in pairs])
        ax.set_title(title)
        ax.set_ylim(0, 0.45)
        ax.yaxis.set_major_formatter(mpl.ticker.PercentFormatter(1.0))
        if ax is axes[0]:
            ax.set_ylabel("Rate (Wilson 95% CI)")
            ax.legend(frameon=False, fontsize=8)

    fig.suptitle("Held-out runtime perturbation (same seed nominal poses)", y=1.02)
    fig.tight_layout()
    out = root / "artifacts/figures/eval/env_a_vs_b"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
    print(f"[plot] {out.with_suffix('.png')}")

    # Paired flip table
    for name, pa, pb, _ in pairs:
        sa, sb = load(pa), load(pb)
        a = {r["episode"]: r["success"] for r in sa["results"]}
        b = {r["episode"]: r["success"] for r in sb["results"]}
        ab = sum(1 for e in a if a[e] and not b.get(e))
        ba = sum(1 for e in a if (not a[e]) and b.get(e))
        print(f"[paired] {name}: EnvA✓/EnvB✗={ab}  EnvA✗/EnvB✓={ba}")


if __name__ == "__main__":
    main()
