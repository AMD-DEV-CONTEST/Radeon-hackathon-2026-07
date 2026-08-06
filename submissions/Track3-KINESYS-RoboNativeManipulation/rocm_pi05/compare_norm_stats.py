"""Compare two norm_stats.json files produced by compute_norm_stats.py.

Prints per-key (state/actions) and per-statistic (mean/std/q01/q99) absolute/relative
differences, plus a side-by-side per-dimension table. Useful for comparing any two
norm_stats files (e.g. before/after a stats change, or across two datasets).

Usage:
  python3 compare_norm_stats.py <a.json> <b.json> [--label-a A] [--label-b B]
"""
import argparse
import json

import numpy as np


def load(p):
    d = json.load(open(p))
    return d["norm_stats"] if "norm_stats" in d else d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--digits", type=int, default=5)
    args = ap.parse_args()

    a, b = load(args.a), load(args.b)
    print(f"Comparing:\n  [{args.label_a}] {args.a}\n  [{args.label_b}] {args.b}\n")

    keys = [k for k in a if k in b]
    overall_max_abs = 0.0
    overall_max_rel = 0.0
    for key in keys:
        print(f"=== {key} (dim={len(a[key]['mean'])}) ===")
        print(f"{'stat':<6}{'max_abs':>14}{'mean_abs':>14}{'max_rel(%)':>12}{'@dim':>7}")
        for stat in ["mean", "std", "q01", "q99"]:
            if a[key].get(stat) is None or b[key].get(stat) is None:
                print(f"  {stat}: (null in one side) a={a[key].get(stat)} b={b[key].get(stat)}")
                continue
            va = np.asarray(a[key][stat], dtype=np.float64)
            vb = np.asarray(b[key][stat], dtype=np.float64)
            if va.shape != vb.shape:
                print(f"  {stat}: shape mismatch {va.shape} vs {vb.shape}")
                continue
            absdiff = np.abs(va - vb)
            denom = np.maximum(np.abs(vb), 1e-8)
            reldiff = absdiff / denom * 100.0
            mx_abs, mx_rel = float(absdiff.max()), float(reldiff.max())
            overall_max_abs = max(overall_max_abs, mx_abs)
            overall_max_rel = max(overall_max_rel, mx_rel)
            print(f"{stat:<6}{mx_abs:>14.3e}{float(absdiff.mean()):>14.3e}{mx_rel:>11.4f}%{int(absdiff.argmax()):>7}")
        print()

    # Per-dimension side-by-side for mean / q99 (most diagnostic).
    for key in keys:
        for stat in ["mean", "q99"]:
            if a[key].get(stat) is None:
                continue
            va = np.asarray(a[key][stat], dtype=np.float64).round(args.digits)
            vb = np.asarray(b[key][stat], dtype=np.float64).round(args.digits)
            print(f"--- {key}.{stat} per-dim ---")
            print(f"  {args.label_a}: {va.tolist()}")
            print(f"  {args.label_b}: {vb.tolist()}")

    print(f"\nOVERALL: max_abs={overall_max_abs:.3e}  max_rel={overall_max_rel:.4f}%")


if __name__ == "__main__":
    main()
