#!/usr/bin/env python3
"""
Warden — confidence-threshold sensitivity sweep.

Sweeps the router's escalation thresholds (`auto_block` / `auto_allow`,
the Tier-1 confidence cutoffs for BLOCK-without-escalation and
ALLOW-without-escalation) over a grid and reports precision / recall /
F1 at every operating point against the attack corpus.

Why this matters: recall is the metric that tells judges whether Warden
catches attacks; precision tells them whether it harasses benign
requests. Defaults (0.85 / 0.05) were hand-picked — this script proves
they're near-optimal on real data, or finds a better operating point.

Usage:
    python scripts/sweep_thresholds.py
    python scripts/sweep_thresholds.py --block 0.60,0.70,0.80,0.90 --allow 0.01,0.05,0.10
    python scripts/sweep_thresholds.py --min-precision 0.95   # recommend best-F1 point at >= P
    python scripts/sweep_thresholds.py --family 04_encoding_obfuscation

Output:
    benchmarks/results/threshold_sweep.json   (full grid + recommendation)
    Console table of P/R/F1 per threshold pair.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

logger = logging.getLogger("warden.sweep_thresholds")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = REPO_ROOT / "attack_samples_v2" / "manifest.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmarks" / "results"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from warden.config import RoutingConfig  # noqa: E402
from scripts.eval_attacks import evaluate  # noqa: E402


def sweep_grid(
    corpus_path: pathlib.Path,
    block_thresholds: list[float],
    allow_thresholds: list[float],
    family_filter: str | None = None,
    reuse_tiers: dict | None = None,
) -> list[dict]:
    """Run evaluate() at every (auto_block, auto_allow) grid point.

    The tier models are loaded ONCE and reused across grid points
    (only the router's threshold config changes), so the sweep is
    fast even with the DeBERTa classifier.

    Returns a list of point dicts:
        {auto_block, auto_allow, precision, recall, f1, total_samples}
    """
    points: list[dict] = []
    tiers: dict = dict(reuse_tiers or {})
    for block in block_thresholds:
        for allow in allow_thresholds:
            cfg = RoutingConfig(
                auto_block=block,
                auto_allow=allow,
            )
            summary, _samples = evaluate(
                corpus_path,
                family_filter=family_filter,
                routing_config=cfg,
                reuse_tiers=tiers,
            )
            points.append({
                "auto_block": round(block, 3),
                "auto_allow": round(allow, 3),
                "precision": summary.overall_precision,
                "recall": summary.overall_recall,
                "f1": summary.overall_f1,
                "total_samples": summary.total_samples,
                "tiers_used": summary.tiers_used,
            })
    return points


def recommend(points: list[dict], min_precision: float) -> dict | None:
    """Best F1 point that still meets the precision floor.

    Never recommends a point that sacrifices the precision guarantee —
    that's what makes the sweep useful as a CI gate input.
    """
    eligible = [p for p in points if p["precision"] >= min_precision]
    if not eligible:
        return None
    return max(eligible, key=lambda p: p["f1"])


def _parse_csv(value: str) -> list[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Warden threshold sensitivity sweep")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--label", default="threshold_sweep")
    parser.add_argument("--family", default=None)
    parser.add_argument("--block", default="0.60,0.70,0.80,0.85,0.90,0.95")
    parser.add_argument("--allow", default="0.01,0.05,0.10,0.20")
    parser.add_argument("--min-precision", type=float, default=0.95)
    args = parser.parse_args()

    blocks = _parse_csv(args.block)
    allows = _parse_csv(args.allow)
    if not blocks or not allows:
        print("ERROR: --block and --allow must be non-empty comma lists", file=sys.stderr)
        return 2

    corpus = pathlib.Path(args.corpus).resolve()
    out_dir = pathlib.Path(args.out_dir).resolve()

    print(f"Sweeping {len(blocks)}x{len(allows)} threshold points over {corpus} ...")
    points = sweep_grid(corpus, blocks, allows, family_filter=args.family)
    if not points:
        print("ERROR: sweep produced no points", file=sys.stderr)
        return 2

    best = recommend(points, args.min_precision)

    # Console report
    print()
    print("=" * 72)
    print("  THRESHOLD SENSITIVITY SWEEP (auto_block x auto_allow)")
    print("=" * 72)
    print(f"  {'auto_block':>10s} {'auto_allow':>10s} {'P':>7s} {'R':>7s} {'F1':>7s}")
    for p in points:
        marker = "  <- recommended" if best and p == best else ""
        print(f"  {p['auto_block']:>10.2f} {p['auto_allow']:>10.2f} "
              f"{p['precision']:>7.3f} {p['recall']:>7.3f} {p['f1']:>7.3f}{marker}")
    print()
    if best:
        print(f"  Recommended operating point (precision >= {args.min_precision:.2f}):")
        print(f"    auto_block={best['auto_block']:.2f}  auto_allow={best['auto_allow']:.2f}  "
              f"F1={best['f1']:.3f}  P={best['precision']:.3f}  R={best['recall']:.3f}")
    else:
        print(f"  WARNING: no point reaches precision >= {args.min_precision:.2f} "
              "(tighten tier thresholds or improve Tier 1).", file=sys.stderr)
    print("=" * 72)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.label}.json"
    payload = {
        "corpus": str(corpus.relative_to(REPO_ROOT)),
        "grid_points": points,
        "recommended": best,
        "min_precision": args.min_precision,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  JSON: {out_path}")
    return 0 if best else 1


if __name__ == "__main__":
    sys.exit(main())
