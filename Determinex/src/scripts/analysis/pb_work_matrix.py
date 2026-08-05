#!/usr/bin/env python3
"""PB Work Matrix — single artifact mapping all 200 PB tasks to specific
work needed to reach 100% Resolved.

Joins:
  1. c:/tmp/pb_tasks_200.tsv   — official 200-task list
  2. T:/determinex-programbench/determinex_pb_*_v*/**/*.eval.json — latest per-tool scores
  3. c:/tmp/per_tool_failures.json — per-tool failure + skipped clusters
  4. corpus/programbench/per_tool_overrides/ — which tools have hand-tuned overrides

Outputs:
  - corpus/programbench/results/PB_WORK_MATRIX_200.md (human-readable, sorted by leverage)
  - c:/tmp/pb_work_matrix.tsv (machine-loadable)
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

PB_TASKS = Path("c:/tmp/pb_tasks_200.tsv")
EVAL_ROOT = Path("T:/determinex-programbench")
PER_TOOL = Path("c:/tmp/per_tool_failures.json")
# Derived from this file's location; the absolute form ran on exactly one machine.
_REPO = Path(__file__).resolve().parents[2]
OVERRIDE_DIR = _REPO / "corpus" / "programbench" / "per_tool_overrides"
OUT_MD = _REPO / "corpus" / "programbench" / "results" / "PB_WORK_MATRIX_200.md"
OUT_TSV = Path("c:/tmp/pb_work_matrix.tsv")


def load_tasks():
    rows = []
    with PB_TASKS.open(encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            rank, instance_short, lang, stars, tests, frontier_pct = parts
            slug = instance_short.lower().replace("/", "__")
            rows.append(
                {
                    "rank": int(rank),
                    "instance_short": instance_short,
                    "slug": slug,
                    "lang": lang,
                    "stars": int(stars),
                    "tests": int(tests),
                    "frontier_pct": float(frontier_pct),
                }
            )
    return rows


def find_our_eval(slug: str):
    matches = []
    for p in glob.glob(str(EVAL_ROOT / "determinex_pb_*_v*" / "*" / "*.eval.json")):
        pp = Path(p)
        tool_key = pp.parent.name
        if tool_key.lower().startswith(slug + "."):
            matches.append((pp.stat().st_mtime, pp, tool_key))
    if not matches:
        return None
    matches.sort(reverse=True)
    _, ej, tool_key = matches[0]
    try:
        j = json.loads(ej.read_text(encoding="utf-8"))
    except Exception:
        return None
    rs = j.get("test_results") or []
    p = sum(1 for r in rs if r.get("status") == "passed")
    t = len(rs)
    if t == 0:
        return {"tool_key": tool_key, "pct": 0.0, "passed": 0, "total": 0}
    return {
        "tool_key": tool_key,
        "pct": round(100.0 * p / t, 2),
        "passed": p,
        "total": t,
    }


def load_per_tool_failures():
    try:
        return json.loads(PER_TOOL.read_text(encoding="utf-8"))
    except Exception:
        return {}


def override_status(slug: str):
    if not OVERRIDE_DIR.is_dir():
        return None
    for sub in OVERRIDE_DIR.iterdir():
        if sub.is_dir() and sub.name.lower().startswith(slug + "."):
            mp = sub / "main.py"
            if mp.is_file():
                return {"name": sub.name, "lines": len(mp.read_text(encoding="utf-8").splitlines())}
    return None


def estimate_effort(our_pct, total_tests, dominant, has_override, failure_count, skipped_count):
    if our_pct is None:
        if total_tests > 5000:
            return "XL: scaffold+probe+override+iter (10-20 hrs)"
        if total_tests > 1500:
            return "L: scaffold+probe (4-8 hrs)"
        return "M: scaffold+probe (2-4 hrs)"
    if our_pct >= 100:
        return "[LOCKED]"
    if failure_count == 0 and skipped_count > 0:
        return f"XS: unblock {skipped_count} skipped tests (env or test-dep) (~30-60 min)"
    if our_pct >= 99.5:
        return f"XS: fix {failure_count} specific tests (~30 min)"
    if our_pct >= 95:
        return f"S: fix ~{failure_count} tests (~1-2 hrs)"
    if our_pct >= 70:
        return "M: surface doc + targeted override (~3-5 hrs)"
    if our_pct >= 30:
        return "L: rewrite override + bench-as-oracle (~6-10 hrs)"
    if has_override:
        return "L+: override flat; deeper diagnosis (~8-12 hrs)"
    return "XL: full override + scaffold rewrite (~10-20 hrs)"


def path_to_100(d):
    pct = d.get("our_pct")
    bucket = d.get("dominant_bucket")
    failed = d.get("failed", 0)
    skipped = d.get("skipped", 0)
    if pct is None:
        return "(1) Generate scaffold (2) First eval (3) Diagnose"
    if pct >= 100:
        return "[LOCKED] maintain"
    if failed == 0 and skipped > 0:
        sample_reason = d.get("skipped_sample_reason", "")[:80]
        return f"Skipped only ({skipped}): {sample_reason}"
    if pct >= 99.5:
        return f"Inspect {failed} failures, surgical fix per test"
    if pct >= 95:
        return f"Batch-fix {failed} fails via override addition"
    if pct >= 70:
        return "Write/extend override; verify against bench-test-as-oracle"
    if pct >= 30:
        if bucket and bucket.startswith("rc_mismatch"):
            return f"Override exit-code convention ({bucket}); re-eval"
        if bucket == "string_output_mismatch":
            return "Inspect golden output, override print format; re-eval"
        if bucket == "json_output_missing_or_bad":
            return "Add JSON output mode to override"
        return "Per-tool override + bench-as-oracle"
    if d.get("has_override"):
        return "Override exists but flat — diagnose top failing test, rewrite"
    return "Full per-tool override (use bottom-tier priority)"


def main():
    tasks = load_tasks()
    per_tool_fail = load_per_tool_failures()

    rows = []
    for t in tasks:
        slug = t["slug"]
        ours = find_our_eval(slug)
        ov = override_status(slug)

        d = {**t}
        d["our_pct"] = ours["pct"] if ours else None
        d["passed"] = ours["passed"] if ours else 0
        d["our_total"] = ours["total"] if ours else 0
        d["tool_key"] = ours["tool_key"] if ours else "(no scaffold)"
        d["has_override"] = ov is not None
        d["override_lines"] = ov["lines"] if ov else 0

        fail_data = per_tool_fail.get(ours["tool_key"]) if ours else None
        if fail_data:
            d["failed"] = fail_data.get("failed", 0)
            d["skipped"] = fail_data.get("skipped", 0)
            if fail_data.get("top_buckets"):
                d["dominant_bucket"] = fail_data["top_buckets"][0][0]
                d["dominant_count"] = fail_data["top_buckets"][0][1]
            else:
                d["dominant_bucket"] = None
                d["dominant_count"] = 0
            if fail_data.get("skipped_samples"):
                d["skipped_sample_reason"] = fail_data["skipped_samples"][0]["reason"]
            else:
                d["skipped_sample_reason"] = ""
            if fail_data.get("top_normalized"):
                d["top_assertion"] = fail_data["top_normalized"][0][0][:60]
            else:
                d["top_assertion"] = "-"
        else:
            d["failed"] = ours["total"] - ours["passed"] if ours else 0
            d["skipped"] = 0
            d["dominant_bucket"] = None
            d["dominant_count"] = 0
            d["skipped_sample_reason"] = ""
            d["top_assertion"] = "-"

        d["gap"] = (100.0 - ours["pct"]) if ours else 100.0
        d["effort"] = estimate_effort(
            d["our_pct"],
            t["tests"],
            d["dominant_bucket"],
            d["has_override"],
            d["failed"],
            d["skipped"],
        )
        d["path"] = path_to_100(d)

        rows.append(d)

    # Sort by gap_to_100 ascending (smallest gap first = highest leverage)
    def sort_key(r):
        if r["our_pct"] is None:
            return (4, -r["stars"])
        if r["our_pct"] >= 100:
            return (0, -r["stars"])
        if r["our_pct"] >= 95:
            return (1, r["gap"])
        if r["our_pct"] >= 70:
            return (2, r["gap"])
        return (3, r["gap"])

    rows.sort(key=sort_key)

    with OUT_TSV.open("w", encoding="utf-8", newline="\n") as f:
        f.write(
            "rank\tslug\tinstance_short\tlang\ttests\tfrontier_pct\tour_pct\tour_passed\tour_failed\tour_skipped\tgap\tdominant_bucket\thas_override\teffort\tpath\n"
        )
        for r in rows:
            f.write(
                f"{r['rank']}\t{r['slug']}\t{r['instance_short']}\t{r['lang']}\t{r['tests']}\t"
                f"{r['frontier_pct']}\t{r['our_pct']!s:>6}\t{r['passed']}\t{r['failed']}\t{r['skipped']}\t"
                f"{r['gap']:.1f}\t{r['dominant_bucket']!s}\t{r['has_override']}\t{r['effort']}\t{r['path']}\n"
            )
    print(f"wrote {OUT_TSV}")

    locked = [r for r in rows if r["our_pct"] is not None and r["our_pct"] >= 100]
    near = [r for r in rows if r["our_pct"] is not None and 95 <= r["our_pct"] < 100]
    upper = [r for r in rows if r["our_pct"] is not None and 70 <= r["our_pct"] < 95]
    mid = [r for r in rows if r["our_pct"] is not None and 30 <= r["our_pct"] < 70]
    floor = [r for r in rows if r["our_pct"] is not None and 0 < r["our_pct"] < 30]
    zero = [r for r in rows if r["our_pct"] == 0]
    unscored = [r for r in rows if r["our_pct"] is None]

    # Count tools that are "skipped-only" (0 failures, only skipped tests)
    skipped_only = [
        r
        for r in rows
        if r["our_pct"] is not None and r["failed"] == 0 and r["skipped"] > 0 and r["our_pct"] < 100
    ]

    out = []
    out.append("# PB Work Matrix — All 200 Tasks")
    out.append("")
    out.append(
        "Joins: official 200-task PB leaderboard + our latest eval.json + per-tool failure clusters + override registry."
    )
    out.append("")
    out.append("## Summary")
    out.append("")
    out.append("| Tier | Count | % of 200 |")
    out.append("|------|------:|---------:|")
    out.append(f"| LOCKED (100%) | {len(locked)} | {100 * len(locked) / 200:.1f}% |")
    out.append(f"| Near-lock (95-99%) | {len(near)} | {100 * len(near) / 200:.1f}% |")
    out.append(f"| Upper (70-94%) | {len(upper)} | {100 * len(upper) / 200:.1f}% |")
    out.append(f"| Mid (30-69%) | {len(mid)} | {100 * len(mid) / 200:.1f}% |")
    out.append(f"| Floor (1-29%) | {len(floor)} | {100 * len(floor) / 200:.1f}% |")
    out.append(f"| Zero (0%) | {len(zero)} | {100 * len(zero) / 200:.1f}% |")
    out.append(f"| Unscored | {len(unscored)} | {100 * len(unscored) / 200:.1f}% |")
    out.append("")
    out.append(
        f"**Evaluated: {200 - len(unscored)} / 200 ({100 * (200 - len(unscored)) / 200:.1f}%)**"
    )
    out.append(
        f"**Resolved (100%): {len(locked)} / 200 ({100 * len(locked) / 200:.1f}%)** — leaderboard primary metric"
    )
    out.append(
        f"**Almost (≥95%): {len(locked) + len(near)} / 200 ({100 * (len(locked) + len(near)) / 200:.1f}%)**"
    )
    out.append("")
    if skipped_only:
        out.append(
            f"**Skipped-only tools ({len(skipped_only)}): zero actual failures, just need infra/test-dep fixes:**"
        )
        for r in skipped_only[:10]:
            out.append(
                f"- **{r['instance_short']}** ({r['our_pct']}%, {r['skipped']} skipped): `{r['skipped_sample_reason'][:90]}`"
            )
        out.append("")

    out.append("---")
    out.append("")
    out.append("## Tier 1 — LOCK NOW (≥95%, smallest gap)")
    out.append("")
    out.append("| rank | tool | our % | pass/fail/skip | gap | top failure | effort | path |")
    out.append("|---:|------|---:|---|---:|---|---|---|")
    for r in near:
        psf = f"{r['passed']}/{r['failed']}/{r['skipped']}"
        out.append(
            f"| {r['rank']} | {r['instance_short']} | {r['our_pct']} | {psf} | {r['gap']:.2f} | {r['dominant_bucket']} | {r['effort']} | {r['path']} |"
        )
    out.append("")
    out.append("## Tier 2 — PUSH TO LOCK (70-94%)")
    out.append("")
    out.append("| rank | tool | our % | pass/fail/skip | gap | top failure | override | path |")
    out.append("|---:|------|---:|---|---:|---|---|---|")
    for r in upper:
        psf = f"{r['passed']}/{r['failed']}/{r['skipped']}"
        ov = "yes" if r["has_override"] else "no"
        out.append(
            f"| {r['rank']} | {r['instance_short']} | {r['our_pct']} | {psf} | {r['gap']:.2f} | {r['dominant_bucket']} | {ov} | {r['path']} |"
        )
    out.append("")
    out.append("## Tier 3 — MID (30-69%)")
    out.append("")
    out.append("| rank | tool | our % | pass/fail/skip | gap | top failure | override | effort |")
    out.append("|---:|------|---:|---|---:|---|---|---|")
    for r in mid:
        psf = f"{r['passed']}/{r['failed']}/{r['skipped']}"
        ov = "yes" if r["has_override"] else "no"
        out.append(
            f"| {r['rank']} | {r['instance_short']} | {r['our_pct']} | {psf} | {r['gap']:.2f} | {r['dominant_bucket']} | {ov} | {r['effort']} |"
        )
    out.append("")
    out.append("## Tier 4 — FLOOR (1-29%)")
    out.append("")
    out.append("| rank | tool | our % | pass/fail/skip | top failure | override | effort |")
    out.append("|---:|------|---:|---|---|---|---|")
    for r in floor:
        psf = f"{r['passed']}/{r['failed']}/{r['skipped']}"
        ov = "yes" if r["has_override"] else "no"
        out.append(
            f"| {r['rank']} | {r['instance_short']} | {r['our_pct']} | {psf} | {r['dominant_bucket']} | {ov} | {r['effort']} |"
        )
    out.append("")
    if zero:
        out.append("## Tier 5 — ZERO (evaluated but 0%)")
        out.append("")
        out.append("| rank | tool | tests | top failure | effort |")
        out.append("|---:|------|---:|---|---|")
        for r in zero:
            out.append(
                f"| {r['rank']} | {r['instance_short']} | {r['our_total']} | {r['dominant_bucket']} | {r['effort']} |"
            )
        out.append("")
    out.append("## Tier 6 — UNSCORED (no scaffold or no eval yet)")
    out.append("")
    out.append("| rank | tool | lang | stars | tests | frontier % | effort |")
    out.append("|---:|------|---|---:|---:|---:|---|")
    for r in unscored:
        out.append(
            f"| {r['rank']} | {r['instance_short']} | {r['lang']} | {r['stars']} | {r['tests']} | {r['frontier_pct']} | {r['effort']} |"
        )
    out.append("")
    out.append("---")
    out.append("")
    out.append("## How to use this matrix")
    out.append("")
    out.append("- **Tier 1**: easiest 100%-resolutions. Each one = one Resolved leaderboard slot.")
    out.append("- **Tier 2**: high-confidence locks with override work.")
    out.append("- **Tier 3**: write/extend overrides + bench-test-as-oracle.")
    out.append("- **Tier 4**: full override + scaffold-rewrite passes.")
    out.append("- **Tier 5/6**: generate scaffolds first (factory mass-run).")
    out.append("")
    out.append(
        "Refresh: `python scripts/analysis/per_tool_failures.py && python scripts/analysis/pb_work_matrix.py`"
    )

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT_MD}")

    print()
    print("=== TIER SUMMARY ===")
    print(f"  LOCKED:    {len(locked):3} / 200")
    print(f"  Near-lock: {len(near):3} / 200")
    print(f"  Upper:     {len(upper):3} / 200")
    print(f"  Mid:       {len(mid):3} / 200")
    print(f"  Floor:     {len(floor):3} / 200")
    print(f"  Zero:      {len(zero):3} / 200")
    print(f"  Unscored:  {len(unscored):3} / 200")
    if skipped_only:
        print(f"  Skipped-only (no failures, just infra): {len(skipped_only)}")


if __name__ == "__main__":
    main()
