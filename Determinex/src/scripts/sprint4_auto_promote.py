#!/usr/bin/env python3
"""sprint4_auto_promote.py — after a tiered eval chain completes, sort the
results into buckets and emit a v2 sprint queue.

Reads:
  logs/mass_run_v2/sprint4_tier<N>_summary.json
Writes:
  logs/mass_run_v2/sprint4_v2_queue.md     (human-readable)
  logs/mass_run_v2/sprint4_v2_queue.json   (machine-readable)
  logs/ledger/sprint4_factory.jsonl        (per-tool ledger event)

Promotion buckets (per user-set thresholds):
  - >=+10pp  : promote_v2   (target for v2 sprint)
  - +3..+10pp: keep_v1      (ship v1, no refinement needed)
  - 0..+3pp  : baseline     (kept but no action)
  - <0pp     : regressed    (discard, log family lesson)
  - infra    : no eval JSON (likely Docker / harness issue)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from run_ledger import LedgerEvent, append_event  # type: ignore[import-not-found]


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-promote factory eval results into v2 queue")
    ap.add_argument("--tier", type=int, required=True, choices=[10, 25, 50, 105])
    ap.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="path to tier summary JSON (default: derive from tier)",
    )
    args = ap.parse_args()

    summary_path = args.summary_json or (
        ROOT / "logs" / "mass_run_v2" / f"sprint4_tier{args.tier}_summary.json"
    )
    if not summary_path.is_file():
        print(f"ERROR: summary not found: {summary_path}")
        return 1
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    buckets = summary.get("buckets", {})

    # Promote_v2 + family stats
    promote_v2 = buckets.get("promote_v2", [])
    keep_v1 = buckets.get("keep_v1", [])
    baseline = buckets.get("baseline", [])
    regressed = buckets.get("regressed", [])
    infra_fail = buckets.get("infra_fail", [])

    fam_lift: dict[str, list[float]] = defaultdict(list)
    for r in promote_v2 + keep_v1 + baseline + regressed:
        d = r.get("delta_pp")
        if d is not None:
            fam_lift[r.get("family", "?")].append(float(d))

    out_md = ROOT / "logs" / "mass_run_v2" / "sprint4_v2_queue.md"
    out_json = ROOT / "logs" / "mass_run_v2" / "sprint4_v2_queue.json"

    lines: list[str] = []
    lines.append(f"# Sprint 4 → v2 Promotion Queue (from tier {args.tier})")
    lines.append("")
    lines.append(
        f"- Evaluated: **{summary.get('elapsed_s', '?')}s** wall, "
        f"avg lift: **{summary.get('avg_lift_pp', '?')} pp**"
    )
    lines.append(f"- Promote to v2 (>=+10pp): **{len(promote_v2)}**")
    lines.append(f"- Keep v1 (+3..+10pp): **{len(keep_v1)}**")
    lines.append(f"- Baseline (0..+3pp): **{len(baseline)}**")
    lines.append(f"- Regressed (<0pp): **{len(regressed)}**")
    lines.append(f"- Infra fail (no JSON): **{len(infra_fail)}**")
    lines.append("")
    lines.append("## v2 Sprint Targets (>=+10pp)")
    lines.append("")
    if promote_v2:
        lines.append("| Rank | Instance | Family | Base % | v1 % | Δ |")
        lines.append("|---:|---|---|---:|---:|---:|")
        for r in sorted(promote_v2, key=lambda x: -float(x.get("delta_pp", 0))):
            lines.append(
                f"| {r.get('rank')} | `{r.get('instance')}` | {r.get('family')} | "
                f"{r.get('base_score')} | {r.get('v1_score')} | **+{r.get('delta_pp')}** |"
            )
    else:
        lines.append("(none yet)")

    lines.append("")
    lines.append("## Family lift summary")
    lines.append("")
    lines.append("| Family | N | Mean Δ | Max Δ | Min Δ |")
    lines.append("|---|---:|---:|---:|---:|")
    for fam in sorted(fam_lift):
        xs = fam_lift[fam]
        if xs:
            lines.append(
                f"| {fam} | {len(xs)} | {sum(xs) / len(xs):+.2f} | {max(xs):+.2f} | {min(xs):+.2f} |"
            )

    if regressed:
        lines.append("")
        lines.append("## Regressions (record family lesson)")
        lines.append("")
        for r in regressed:
            lines.append(
                f"- `{r.get('instance')}` ({r.get('family')}) Δ={r.get('delta_pp')}pp — "
                f"investigate family mixin assumption"
            )

    out_md.write_text("\n".join(lines), encoding="utf-8")

    # JSON
    out_json.write_text(
        json.dumps(
            {
                "from_tier": args.tier,
                "promote_v2": promote_v2,
                "keep_v1": keep_v1,
                "baseline": baseline,
                "regressed": regressed,
                "infra_fail": infra_fail,
                "family_lift": {
                    k: {
                        "n": len(v),
                        "mean": sum(v) / len(v) if v else 0,
                        "max": max(v) if v else 0,
                        "min": min(v) if v else 0,
                    }
                    for k, v in fam_lift.items()
                },
                "total_evaluated": (
                    len(promote_v2)
                    + len(keep_v1)
                    + len(baseline)
                    + len(regressed)
                    + len(infra_fail)
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Ledger events
    for r in promote_v2 + keep_v1 + baseline + regressed:
        bucket = (
            "promote_v2"
            if r in promote_v2
            else "keep_v1"
            if r in keep_v1
            else "baseline"
            if r in baseline
            else "regressed"
        )
        append_event(
            LedgerEvent(
                run_id=f"factory_v1_{r.get('instance')}",
                phase="eval_complete",
                status=bucket,
                score=r.get("v1_score") or 0.0,
                extra={
                    "instance_id": r.get("instance"),
                    "family": r.get("family"),
                    "base_score": r.get("base_score"),
                    "v1_score": r.get("v1_score"),
                    "delta_pp": r.get("delta_pp"),
                    "sprint": "factory_sprint4",
                    "from_tier": args.tier,
                },
            )
        )

    print(f"=== Sprint 4 tier {args.tier} promotion ===")
    print(f"  promote_v2:  {len(promote_v2)}")
    print(f"  keep_v1:     {len(keep_v1)}")
    print(f"  baseline:    {len(baseline)}")
    print(f"  regressed:   {len(regressed)}")
    print(f"  infra fail:  {len(infra_fail)}")
    print(f"  avg lift:    {summary.get('avg_lift_pp', '?')} pp")
    print()
    print(f"  v2 queue md:   {out_md}")
    print(f"  v2 queue json: {out_json}")
    print("  ledger events recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
