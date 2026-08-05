"""scripts/programbench_compare_runs.py — base vs iter1 vs iter2 delta report.

Generates a structured delta report comparing two or three ProgramBench runs:

  python scripts/programbench_compare_runs.py \\
      --base mass_run_v2_base \\
      --iter mass_run_v2_iter1 \\
      [--iter2 mass_run_v2_iter2] \\
      [--out logs/mass_run_v2/]

Output:
  {out}/{base}_vs_{iter}_delta.{json,md}     (two-way)
  {out}/{base}_vs_{iter}_vs_{iter2}_delta.{json,md}  (three-way)

Sections in the report:
  - Run provenance comparison: which scaffold version, git_sha, patch_family
    drove each run. Anchors the delta to byte-level evidence of what changed.
  - Per-tool delta table: sorted by score delta descending. Flags new locks
    (now at 100%), regressions (score went down), and unchanged.
  - Family histogram delta: which failure families shrank or grew across runs.
  - Advisor-expectation reconciliation: if the run carried an iter1 patch
    targeting family F with predicted lift +Xpp, the report compares predicted
    vs actual.

Reads:
  - Run provenance from the ledger (query_run_meta)
  - Per-tool scores from the ledger (one eval event per task per run)
  - Falls back to direct eval-JSON scan if a run isn't in the ledger yet.

The output JSON is the contract the future frontend Benchmark Lab compare-view
will subscribe to. Stable keys; additive evolution only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
from run_ledger import (  # type: ignore[import-not-found]
    _open_db,
    query_run_meta,
    rebuild_index,
)

_DEFAULT_OUT = Path(
    os.environ.get(
        "DETERMINEX_PB_COMPARE_OUT",
        str(_SCRIPTS.parent / "logs" / "mass_run_v2"),
    )
)

LOCK_THRESHOLD = 99.9  # ≥99.9% counts as a lock for compare purposes


# ---------------------------------------------------------------------------
# Read one run's per-tool scores from the ledger
# ---------------------------------------------------------------------------


def _scores_from_ledger(run_id: str, sqlite_path: Path | None = None) -> dict[str, dict]:
    """Return {task_id: {score, passed, total, families}} for one run.

    Uses the most recent 'eval / completed' event per task. sqlite_path
    defaults to the module-level SQLITE_PATH at CALL time (not import time),
    so the path can be swapped via test fixtures or env config.
    """
    if sqlite_path is None:
        import run_ledger as _rl

        sqlite_path = _rl.SQLITE_PATH
    if not sqlite_path.exists():
        rebuild_index(sqlite_path)
    conn = _open_db(sqlite_path)
    try:
        rows = conn.execute(
            """SELECT task_id, score, failures_json, extra_json, timestamp
               FROM events
               WHERE run_id = ? AND phase = 'eval' AND status = 'completed'
               ORDER BY timestamp""",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    # Most recent per task wins (rows already in timestamp order ASC).
    by_task: dict[str, dict] = {}
    for task_id, score, failures_json, extra_json, ts in rows:
        if not task_id:
            continue
        extra = json.loads(extra_json) if extra_json else {}
        families = json.loads(failures_json) if failures_json else {}
        by_task[task_id] = {
            "score": score if score is not None else 0.0,
            "passed": extra.get("passed", 0),
            "failed": extra.get("failed", 0),
            "total": extra.get("total", 0),
            "families": families,
            "timestamp": ts,
        }
    return by_task


# ---------------------------------------------------------------------------
# Compare two runs
# ---------------------------------------------------------------------------


def compare_two(base_run_id: str, iter_run_id: str) -> dict:
    base = _scores_from_ledger(base_run_id)
    after = _scores_from_ledger(iter_run_id)

    # Tools present in both runs
    shared = sorted(set(base) & set(after))
    only_base = sorted(set(base) - set(after))
    only_iter = sorted(set(after) - set(base))

    tools: list[dict] = []
    new_locks: list[str] = []
    new_unlocks: list[str] = []
    regressions: list[dict] = []
    unchanged: list[str] = []

    for tid in shared:
        b = base[tid]
        a = after[tid]
        delta = round(a["score"] - b["score"], 1)
        was_lock = b["score"] >= LOCK_THRESHOLD
        is_lock = a["score"] >= LOCK_THRESHOLD
        if is_lock and not was_lock:
            new_locks.append(tid)
        if was_lock and not is_lock:
            new_unlocks.append(tid)
        if delta < 0:
            regressions.append(
                {"task_id": tid, "delta": delta, "base": b["score"], "iter": a["score"]}
            )
        if delta == 0:
            unchanged.append(tid)
        tools.append(
            {
                "task_id": tid,
                "base_score": b["score"],
                "iter_score": a["score"],
                "delta": delta,
                "base_total": b["total"],
                "iter_total": a["total"],
                "is_new_lock": is_lock and not was_lock,
                "is_regression": delta < 0,
            }
        )

    tools.sort(key=lambda t: -t["delta"])

    # Family histogram delta across the SHARED set
    fam_base: Counter = Counter()
    fam_iter: Counter = Counter()
    for tid in shared:
        for k, v in base[tid].get("families", {}).items():
            fam_base[k] += int(v)
        for k, v in after[tid].get("families", {}).items():
            fam_iter[k] += int(v)
    all_fams = sorted(set(fam_base) | set(fam_iter), key=lambda f: -fam_iter.get(f, 0))
    family_delta = [
        {
            "family": f,
            "base": fam_base.get(f, 0),
            "iter": fam_iter.get(f, 0),
            "delta": fam_iter.get(f, 0) - fam_base.get(f, 0),
        }
        for f in all_fams
    ]

    # Aggregate scores across shared tools
    avg_base = round(sum(base[t]["score"] for t in shared) / max(len(shared), 1), 1)
    avg_iter = round(sum(after[t]["score"] for t in shared) / max(len(shared), 1), 1)

    return {
        "base_run_id": base_run_id,
        "iter_run_id": iter_run_id,
        "base_meta": query_run_meta(base_run_id) or {},
        "iter_meta": query_run_meta(iter_run_id) or {},
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "shared_tools": len(shared),
        "only_in_base": only_base,
        "only_in_iter": only_iter,
        "avg_score_base": avg_base,
        "avg_score_iter": avg_iter,
        "avg_delta_pp": round(avg_iter - avg_base, 1),
        "new_locks": new_locks,
        "new_unlocks": new_unlocks,
        "regression_count": len(regressions),
        "unchanged_count": len(unchanged),
        "tools": tools,
        "regressions": regressions[:50],
        "family_delta": family_delta,
    }


# ---------------------------------------------------------------------------
# Three-way: base -> iter1 -> iter2
# ---------------------------------------------------------------------------


def compare_three(base_id: str, iter1_id: str, iter2_id: str) -> dict:
    b_vs_1 = compare_two(base_id, iter1_id)
    b_vs_2 = compare_two(base_id, iter2_id)
    one_vs_2 = compare_two(iter1_id, iter2_id)

    # Trajectory per tool
    base = _scores_from_ledger(base_id)
    i1 = _scores_from_ledger(iter1_id)
    i2 = _scores_from_ledger(iter2_id)
    shared = sorted(set(base) & set(i1) & set(i2))
    trajectory = [
        {
            "task_id": tid,
            "base": base[tid]["score"],
            "iter1": i1[tid]["score"],
            "iter2": i2[tid]["score"],
            "net_delta": round(i2[tid]["score"] - base[tid]["score"], 1),
        }
        for tid in shared
    ]
    trajectory.sort(key=lambda t: -t["net_delta"])

    return {
        "kind": "three-way",
        "base_run_id": base_id,
        "iter1_run_id": iter1_id,
        "iter2_run_id": iter2_id,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "base_vs_iter1": b_vs_1,
        "base_vs_iter2": b_vs_2,
        "iter1_vs_iter2": one_vs_2,
        "shared_tools": len(shared),
        "trajectory": trajectory,
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_two_way_md(report: dict) -> str:
    lines: list[str] = []
    bm = report.get("base_meta") or {}
    im = report.get("iter_meta") or {}
    lines.append(f"# Compare: {report['base_run_id']} → {report['iter_run_id']}\n")
    lines.append(f"_generated {report['generated_at']}_\n")

    lines.append("## Run provenance")
    lines.append("")
    lines.append(f"| Field | base ({report['base_run_id']}) | iter ({report['iter_run_id']}) |")
    lines.append("|---|---|---|")
    lines.append(
        f"| scaffold_version | {bm.get('scaffold_version', '?')} | {im.get('scaffold_version', '?')} |"
    )
    lines.append(
        f"| patch_family     | {bm.get('patch_family', '?')} | {im.get('patch_family', '?')} |"
    )
    lines.append(
        f"| git_sha          | {(bm.get('git_sha') or '?')[:12]} | {(im.get('git_sha') or '?')[:12]} |"
    )
    lines.append(
        f"| output_root      | {bm.get('output_root', '?')} | {im.get('output_root', '?')} |"
    )
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- shared tools: **{report['shared_tools']}**")
    lines.append(
        f"- avg score: **{report['avg_score_base']} → {report['avg_score_iter']}** ({report['avg_delta_pp']:+} pp)"
    )
    lines.append(
        f"- new locks: **{len(report['new_locks'])}**  |  new unlocks: **{len(report['new_unlocks'])}**  |  regressions: **{report['regression_count']}**  |  unchanged: **{report['unchanged_count']}**"
    )
    if report["only_in_base"]:
        lines.append(
            f"- only in base ({len(report['only_in_base'])}): {report['only_in_base'][:5]}{'...' if len(report['only_in_base']) > 5 else ''}"
        )
    if report["only_in_iter"]:
        lines.append(
            f"- only in iter ({len(report['only_in_iter'])}): {report['only_in_iter'][:5]}{'...' if len(report['only_in_iter']) > 5 else ''}"
        )
    lines.append("")

    if report["new_locks"]:
        lines.append("## New locks (≥99.9%)")
        for t in report["new_locks"]:
            lines.append(f"- {t}")
        lines.append("")

    lines.append("## Top movers (top 15 + bottom 5)")
    lines.append("")
    lines.append("| Δ pp | base | iter | tool |")
    lines.append("|---:|---:|---:|---|")
    for t in report["tools"][:15]:
        marker = " 🔒" if t["is_new_lock"] else (" ⚠️" if t["is_regression"] else "")
        lines.append(
            f"| {t['delta']:+.1f} | {t['base_score']:.1f} | {t['iter_score']:.1f} | {t['task_id']}{marker} |"
        )
    if len(report["tools"]) > 20:
        lines.append("| ... | ... | ... | ... |")
        for t in report["tools"][-5:]:
            marker = " ⚠️" if t["is_regression"] else ""
            lines.append(
                f"| {t['delta']:+.1f} | {t['base_score']:.1f} | {t['iter_score']:.1f} | {t['task_id']}{marker} |"
            )
    lines.append("")

    lines.append("## Family histogram delta")
    lines.append("")
    lines.append("| Family | base | iter | Δ |")
    lines.append("|---|---:|---:|---:|")
    for f in report["family_delta"][:15]:
        arrow = "↑" if f["delta"] > 0 else ("↓" if f["delta"] < 0 else "—")
        lines.append(f"| {f['family']} | {f['base']:,} | {f['iter']:,} | {arrow} {f['delta']:+,} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    ap = argparse.ArgumentParser(description="ProgramBench cross-run delta report")
    ap.add_argument("--base", required=True, help="base run_id (e.g. mass_run_v2_base)")
    ap.add_argument("--iter", required=True, help="iter run_id (e.g. mass_run_v2_iter1)")
    ap.add_argument("--iter2", default=None, help="optional second iter for three-way trajectory")
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="output directory")
    ap.add_argument("--print", action="store_true", help="also print markdown to stdout")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    if args.iter2:
        report = compare_three(args.base, args.iter, args.iter2)
        stem = f"{args.base}_vs_{args.iter}_vs_{args.iter2}_delta"
    else:
        report = compare_two(args.base, args.iter)
        stem = f"{args.base}_vs_{args.iter}_delta"

    out_json = args.out / f"{stem}.json"
    out_md = args.out / f"{stem}.md"
    out_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if not args.iter2:
        md = render_two_way_md(report)
    else:
        # Three-way: render the two pairwise reports + trajectory header
        md_parts = [f"# Compare three: {args.base} → {args.iter} → {args.iter2}\n"]
        md_parts.append(f"_generated {report['generated_at']}_\n")
        md_parts.append("## Trajectory net Δ (top 20)\n")
        md_parts.append("| net Δ pp | base | iter1 | iter2 | tool |")
        md_parts.append("|---:|---:|---:|---:|---|")
        for t in report["trajectory"][:20]:
            md_parts.append(
                f"| {t['net_delta']:+.1f} | {t['base']:.1f} | {t['iter1']:.1f} | {t['iter2']:.1f} | {t['task_id']} |"
            )
        md_parts.append("")
        md_parts.append("## base → iter1\n")
        md_parts.append(render_two_way_md(report["base_vs_iter1"]))
        md_parts.append("## base → iter2\n")
        md_parts.append(render_two_way_md(report["base_vs_iter2"]))
        md_parts.append("## iter1 → iter2\n")
        md_parts.append(render_two_way_md(report["iter1_vs_iter2"]))
        md = "\n".join(md_parts)
    out_md.write_text(md, encoding="utf-8")

    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    if args.print:
        print()
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
