"""Spread across random seeds, so a reported difference can be told from noise.

Every configuration had been run exactly once, and several of the differences
being claimed are a few per cent. This reports the mean and the seed-to-seed
standard deviation for each arm, then expresses each difference as a multiple
of that spread. Anything under about 1.5x is noise wearing a decimal point.

    python -m scripts.error_bars
"""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

RUNS = Path("/data/quakesense/runs")

GROUPS = {
    "k=0%": ["ab_city_k000"] + [f"ab_rep_k000_s{s}" for s in (101, 202, 303)],
    "k=30%": ["ab_city_k030"] + [f"ab_rep_k030_s{s}" for s in (101, 202, 303)],
    "k=100%": ["ab_city_k100"] + [f"ab_rep_k100_s{s}" for s in (101, 202, 303)],
    "LLM,k=0%": ["ab_city_llm000"] + [f"ab_rep_llm000_s{s}" for s in (101, 202)],
}

METRICS = [
    ("sheltered", "{:,.0f}"),
    ("share_safe_by_15min", "{:.4%}"),
    ("t_p50_min_of_sheltered", "{:.2f}"),
    ("median_dist_walked_m", "{:.1f}"),
]


def collect():
    out = {}
    for g, runs in GROUPS.items():
        vals = {m: [] for m, _ in METRICS}
        for r in runs:
            f = RUNS / r / "summary.json"
            if not f.exists():
                continue
            t = json.loads(f.read_text(encoding="utf-8"))["totals"]
            for m, _ in METRICS:
                vals[m].append(float(t.get(m, 0.0)))
        if any(vals[m] for m, _ in METRICS):
            out[g] = vals
    return out


def main():
    data = collect()
    hdr = f"{'group':<10}{'n':>3}  " + "".join(f"{m:>30}" for m, _ in METRICS)
    print(hdr)
    print("-" * len(hdr))
    for g, vals in data.items():
        n = len(vals[METRICS[0][0]])
        row = f"{g:<10}{n:>3}  "
        for m, fmt in METRICS:
            v = vals[m]
            mean = st.mean(v)
            sd = st.stdev(v) if len(v) > 1 else 0.0
            rel = sd / abs(mean) * 100 if mean else 0.0
            row += f"{fmt.format(mean):>21} ±{rel:>5.2f}%"
        print(row)

    if "k=0%" not in data:
        return
    print("\nDifference vs k=0%, relative to between-seed standard deviation:")
    base = data["k=0%"]
    for g in [k for k in data if k != "k=0%"]:
        print(f"\n  {g}")
        for m, fmt in METRICS:
            b, v = base[m], data[g][m]
            mb, mv = st.mean(b), st.mean(v)
            sb = st.stdev(b) if len(b) > 1 else 0.0
            sv = st.stdev(v) if len(v) > 1 else 0.0
            pooled = ((sb ** 2 + sv ** 2) / 2) ** 0.5
            diff = mv - mb
            ratio = abs(diff) / pooled if pooled > 0 else float("inf")
            verdict = ("robust" if ratio > 3 else
                       "borderline" if ratio > 1.5 else "within noise")
            pct = diff / mb * 100 if mb else 0.0
            print(f"    {m:<26}{fmt.format(diff):>18}  ({pct:+6.2f}%)  "
                  f"{ratio:>7.1f}x seed standard deviation   {verdict}")


if __name__ == "__main__":
    main()
