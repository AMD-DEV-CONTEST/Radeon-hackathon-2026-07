#!/usr/bin/env python3
"""Paired 50-state analysis for the 300P Q selection / Q guidance additions.

Reads per-state closed_loop_metrics.json under seed_2001/reset_N and prints the
same protocol used elsewhere in this project: success counts, Wilson 95% CI,
failure->success / success->failure transitions vs Base, net change, and exact
two-sided McNemar p.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

STATES = range(50)


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    rate = successes / total
    denom = 1.0 + z * z / total
    center = (rate + z * z / (2.0 * total)) / denom
    radius = (
        z * math.sqrt(rate * (1.0 - rate) / total + z * z / (4.0 * total * total)) / denom
    )
    return center - radius, center + radius


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar p using the binomial tail on discordant pairs."""
    if b + c == 0:
        return 1.0
    n = b + c
    k = min(b, c)
    p = 0.0
    for i in range(k + 1):
        p += math.comb(n, i) * (0.5**n)
    return 2.0 * p if p <= 0.5 else 1.0


def load(root: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for state in STATES:
        rec = json.loads(
            (root / "seed_2001" / f"reset_{state}" / "closed_loop_metrics.json").read_text()
        )
        out[state] = rec
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--method", required=True)
    args = parser.parse_args()

    base = load(args.base_dir)
    cand = load(args.candidate_dir)

    base_success = {s for s, r in base.items() if r["success"]}
    cand_success = {s for s, r in cand.items() if r["success"]}

    f2s = sorted(cand_success - base_success)
    s2f = sorted(base_success - cand_success)
    net = len(f2s) - len(s2f)

    ok = all(r["action_finite"] for r in cand.values())
    successes = len(cand_success)
    lo, hi = wilson(successes, 50)
    mean_success_steps = (
        sum(r["steps"] for s, r in cand.items() if r["success"]) / successes if successes else 0.0
    )
    median_success_steps = sorted(
        r["steps"] for s, r in cand.items() if r["success"]
    )[ (successes - 1) // 2 ] if successes else 0

    print(f"== {args.method} (300P critic) ==")
    print(f"successes: {successes}/50  ({successes/0.5:.1f}%)")
    print(f"wilson95: [{lo:.4f}, {hi:.4f}]")
    print(f"mean_successful_steps: {mean_success_steps:.2f}")
    print(f"median_successful_steps: {median_success_steps}")
    print(f"all_actions_finite: {ok}")
    print(f"failure->success: {f2s}")
    print(f"success->failure: {s2f}")
    print(f"net: {net:+d}")
    print(f"exact_mcnemar_two_sided_p: {exact_mcnemar(len(f2s), len(s2f)):.8g}")


if __name__ == "__main__":
    main()
