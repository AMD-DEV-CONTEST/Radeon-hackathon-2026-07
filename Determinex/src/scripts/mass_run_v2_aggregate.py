#!/usr/bin/env python3
"""Aggregate ProgramBench eval JSONs into a per-tool score table + cross-batch
failure-family ranking for the next iteration target.

CLI:
    python scripts/mass_run_v2_aggregate.py
        [--root T:/determinex-programbench/mass_run_v2_base]
        [--run-id mass_run_v2_base]
        [--phase base|iter1|iter2|...]
        [--out logs/mass_run_v2/]

Defaults preserve the original behavior (reads mass_run_v2_base, writes
base_summary.json + .md to logs/mass_run_v2/). The new flags let the same
aggregator drive iter1/iter2 reports and any future run without code edits.

Output filenames follow `{run_id}_{phase}_summary.{json,md}` so multiple runs
coexist in the same out dir.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

_DEFAULT_ROOT = Path(
    os.environ.get(
        "DETERMINEX_PB_AGGREGATE_ROOT",
        "T:/determinex-programbench/mass_run_v2_base",
    )
)
_DEFAULT_OUT = Path(
    os.environ.get(
        "DETERMINEX_PB_AGGREGATE_OUT",
        str(Path(__file__).resolve().parents[1] / "logs" / "mass_run_v2"),
    )
)


def parse_one(eval_json: Path) -> dict:
    try:
        d = json.loads(eval_json.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"parse: {e}", "instance_id": eval_json.stem.replace(".eval", "")}
    results = d.get("test_results", [])
    passed = sum(1 for r in results if r.get("status") == "passed")
    failed = sum(1 for r in results if r.get("status") == "failure")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    total = passed + failed
    return {
        "instance_id": eval_json.stem.replace(".eval", ""),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": total,
        "score": round(100 * passed / max(total, 1), 1),
        "error_code": d.get("error_code"),
        "results": results,
    }


# Family classification routes through the central taxonomy at
# scripts/determinex_pb_taxonomy.py — this module previously duplicated the
# 19-family regex table. Re-imported here so the older `classify()` callsites
# in this file keep working with no behavior change.
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from determinex_pb_taxonomy import classify_one as classify  # noqa: F401


def aggregate(
    *,
    root: Path = _DEFAULT_ROOT,
    run_id: str = "mass_run_v2_base",
    phase: str = "base",
    out_dir: Path = _DEFAULT_OUT,
) -> dict:
    """Aggregate one run's eval JSONs. Returns the summary dict; also writes
    {out_dir}/{run_id}_{phase}_summary.json and .md."""
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(root.glob("*/*.eval.json"))
    rows = [parse_one(p) for p in files]
    rows.sort(key=lambda r: r.get("score", 0), reverse=True)

    # Cross-batch failure-family histogram (count failed test instances per family)
    family_hits: Counter = Counter()
    family_tools: dict[str, set] = defaultdict(set)
    family_examples: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for r in rows:
        if r.get("error_code") or not r.get("results"):
            continue
        for tr in r["results"]:
            if tr.get("status") != "failure":
                continue
            name = tr.get("name", "")
            extra = tr.get("extra") or {}
            msg = str(extra.get("message", ""))
            fam = classify(name, msg)
            family_hits[fam] += 1
            family_tools[fam].add(r["instance_id"])
            if len(family_examples[fam]) < 3:
                family_examples[fam].append((r["instance_id"], name, msg[:160]))

    total_pass = sum(r.get("passed", 0) for r in rows)
    total_tests = sum(r.get("total", 0) for r in rows)
    avg_score = sum(r.get("score", 0) for r in rows) / max(len(rows), 1)

    summary = {
        "run_id": run_id,
        "phase": phase,
        "root": str(root),
        "tools_evaluated": len(rows),
        "total_tests": total_tests,
        "total_passing": total_pass,
        "pct_passing": round(100 * total_pass / max(total_tests, 1), 1),
        "avg_score_per_tool": round(avg_score, 1),
        "perfect_score_count": sum(1 for r in rows if r.get("score", 0) >= 99.9),
        "zero_score_count": sum(1 for r in rows if r.get("score", 0) == 0),
        "by_tool": [
            {k: r[k] for k in ("instance_id", "passed", "failed", "total", "score") if k in r}
            for r in rows
        ],
        "failure_families": [
            {
                "family": fam,
                "failures": count,
                "tools_affected": len(family_tools[fam]),
                "examples": family_examples[fam],
            }
            for fam, count in family_hits.most_common()
        ],
    }

    stem = f"{run_id}_{phase}" if phase else run_id
    out_json = out_dir / f"{stem}_summary.json"
    out_md = out_dir / f"{stem}_summary.md"
    out_json.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    # Markdown report
    md = []
    md.append(f"# Run {run_id} — Phase: {phase}\n")
    md.append(f"- tools evaluated: **{summary['tools_evaluated']}**")
    md.append(f"- total tests: {total_tests:,}")
    md.append(f"- total passing: {total_pass:,} ({summary['pct_passing']}%)")
    md.append(f"- avg per-tool score: **{summary['avg_score_per_tool']}**")
    md.append(f"- perfect scores: {summary['perfect_score_count']}")
    md.append(f"- zero scores: {summary['zero_score_count']}")
    md.append(f"- eval root: `{root}`")
    md.append("")
    md.append("## Top cross-batch failure families")
    md.append("")
    md.append("| Family | Failures | Tools affected |")
    md.append("|---|---:|---:|")
    for fam in summary["failure_families"][:15]:
        md.append(f"| {fam['family']} | {fam['failures']:,} | {fam['tools_affected']} |")
    md.append("")
    md.append("## Score distribution (top 20 + bottom 20)")
    md.append("")
    md.append("| Score | Pass / Total | Tool |")
    md.append("|---:|---|---|")
    for r in rows[:20]:
        md.append(
            f"| {r.get('score', 0):.1f} | {r.get('passed', 0)} / {r.get('total', 0)} | {r['instance_id']} |"
        )
    if len(rows) > 40:
        md.append("| ... | ... | ... |")
        for r in rows[-20:]:
            md.append(
                f"| {r.get('score', 0):.1f} | {r.get('passed', 0)} / {r.get('total', 0)} | {r['instance_id']} |"
            )
    out_md.write_text("\n".join(md), encoding="utf-8")

    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    print()
    print(
        f"=== {run_id} / {phase} : {summary['tools_evaluated']} tools, avg {summary['avg_score_per_tool']}/100 ==="
    )
    print(f"total: {total_pass:,}/{total_tests:,} ({summary['pct_passing']}%)")
    print(f"perfect: {summary['perfect_score_count']}   zeros: {summary['zero_score_count']}")
    print()
    print("Top failure families:")
    for fam in summary["failure_families"][:10]:
        print(f"  {fam['failures']:>5}  ({fam['tools_affected']:>3} tools)  {fam['family']}")
    return summary


def _cli():
    ap = argparse.ArgumentParser(description="Aggregate one ProgramBench run's eval JSONs")
    ap.add_argument(
        "--root", type=Path, default=_DEFAULT_ROOT, help=f"eval root dir (default: {_DEFAULT_ROOT})"
    )
    ap.add_argument(
        "--run-id",
        default="mass_run_v2_base",
        help="ledger run_id label (also used in output filename)",
    )
    ap.add_argument(
        "--phase", default="base", help="phase label for output filename: base|iter1|iter2|..."
    )
    ap.add_argument(
        "--out", type=Path, default=_DEFAULT_OUT, help=f"output directory (default: {_DEFAULT_OUT})"
    )
    args = ap.parse_args()
    aggregate(root=args.root, run_id=args.run_id, phase=args.phase, out_dir=args.out)


if __name__ == "__main__":
    _cli()
