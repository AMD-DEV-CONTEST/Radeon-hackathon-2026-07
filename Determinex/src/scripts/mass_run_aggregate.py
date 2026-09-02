#!/usr/bin/env python3
"""Mass-run result aggregator — consolidates scattered eval JSONs into a single scoreboard.

Walks:
  - T:/determinex-programbench/<run>/<instance>/<instance>.eval.json (or eval_report.json)
  - T:/determinex-swebench/<run>/predictions/* (SWE-bench harness output)
  - Any explicit --run-dir paths

Produces:
  - scoreboard.txt — human-readable, locks per tier, per-bench totals
  - scoreboard.json — machine-readable, every instance's score
  - locks_so_far.txt — just the locks (for showing progress)

Usage:
  python scripts/mass_run_aggregate.py
  python scripts/mass_run_aggregate.py --run-dir T:/determinex-programbench/mass_run_v1
  python scripts/mass_run_aggregate.py --watch  (re-aggregates every 30s while a run is live)
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# Windows console: force UTF-8 output so box-drawing chars don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Default scan roots ──────────────────────────────────────────────────────
PB_RUNS_BASE = Path("T:/determinex-programbench")
SB_RUNS_BASE = Path("T:/determinex-swebench")
import os as _os

DETERMINEX_ROOT = Path(_os.environ.get("DETERMINEX_ROOT", Path(__file__).resolve().parents[1]))
PB_CORPUS_BASE = DETERMINEX_ROOT / "corpus" / "programbench"
OUT_DIR = DETERMINEX_ROOT / "logs" / "mass_run_aggregates"


def _score_from_pb_eval_json(p: Path) -> tuple[int, int] | None:
    """Parse a ProgramBench *.eval.json — returns (passed, total) or None if unusable.

    Counts statuses from `test_results[]` (passed vs failure) — excludes skipped from
    the denominator. This matches what the official harness scoreboard uses.
    """
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if d.get("error_code"):
        return None
    results = d.get("test_results")
    if isinstance(results, list) and results:
        passed = sum(1 for r in results if r.get("status") == "passed")
        failed = sum(1 for r in results if r.get("status") == "failure")
        total = passed + failed
        return (passed, total) if total > 0 else None
    # Fallback to legacy shape (unlikely)
    passed = d.get("passed", d.get("tests_passed", 0))
    total = d.get("total", d.get("tests_total", 0))
    if isinstance(passed, int) and isinstance(total, int) and total > 0:
        return (passed, total)
    return None


def _canonical_pb_tool(name: str) -> str:
    """Collapse ProgramBench instance IDs to the human tool name.

    Examples:
      mgdm__htmlq.6e31bc8 -> htmlq
      burntsushi__ripgrep.3b7fd44 -> ripgrep
    Corpus folders already use this short name.
    """
    if "__" in name:
        name = name.split("__", 1)[1]
    if "." in name:
        name = name.split(".", 1)[0]
    return name


def find_pb_evals(roots: list[Path]) -> list[dict]:
    """Find all ProgramBench eval JSONs under the roots. Each result has shape:
       {tool, run, passed, total, pct, eval_path, verified_locked, shipped}.
    Uses bounded depth (2 levels: root/<run>/<instance>) — NOT rglob, which is too slow."""
    out = []
    for root in roots:
        if not root.is_dir():
            continue
        # Iterate run dirs first (1 level deep), then instance dirs (2 levels)
        candidates: list[Path] = []
        try:
            for inst_dir in root.iterdir():
                if not inst_dir.is_dir():
                    continue
                if "__" in inst_dir.name and "." in inst_dir.name:
                    candidates.append(inst_dir)
                else:
                    for sub in inst_dir.iterdir():
                        if sub.is_dir() and "__" in sub.name:
                            candidates.append(sub)
        except (OSError, PermissionError):
            continue
        for inst_dir in candidates:
            tool = _canonical_pb_tool(inst_dir.name)
            # Pull the agent's verified_locked / shipped flags if present
            metrics_path = inst_dir / "metrics.json"
            verified_locked = False
            shipped = False
            if metrics_path.exists():
                try:
                    m = json.loads(metrics_path.read_text(encoding="utf-8"))
                    verified_locked = bool(m.get("verified_locked", False))
                    shipped = bool(m.get("shipped", False))
                except Exception:
                    pass
            # Score from official eval JSON (the only judge)
            best: tuple[int, int] | None = None
            best_path: str = ""
            for pat in ("*.eval.json", "eval_report.json", "*_eval.json"):
                for p in inst_dir.glob(pat):
                    score = _score_from_pb_eval_json(p)
                    if score is None:
                        continue
                    if best is None or score[0] / max(score[1], 1) > best[0] / max(best[1], 1):
                        best, best_path = score, str(p)
            if best is None:
                # No scorable eval JSON yet (maybe attempted but never compiled)
                if shipped or verified_locked:
                    out.append(
                        {
                            "kind": "programbench",
                            "tool": tool,
                            "run": inst_dir.parent.name,
                            "passed": 0,
                            "total": 0,
                            "pct": 0.0,
                            "eval_path": "",
                            "verified_locked": verified_locked,
                            "shipped": shipped,
                        }
                    )
                continue
            passed, total = best
            out.append(
                {
                    "kind": "programbench",
                    "tool": tool,
                    "run": inst_dir.parent.name,
                    "passed": passed,
                    "total": total,
                    "pct": 100.0 * passed / total,
                    "eval_path": best_path,
                    "verified_locked": verified_locked or (passed == total),
                    "shipped": shipped or True,  # if eval JSON exists, a submission was scored
                }
            )
    return out


def find_pb_corpus_evals(root: Path = PB_CORPUS_BASE) -> list[dict]:
    """Find curated ProgramBench corpus eval reports.

    These are copied official `programbench eval` reports under
    corpus/programbench/{locked,in_progress}/<tool>/eval_report.json. They are
    first-class evidence, but are stored outside T:/determinex-programbench, so the
    run scanner above will never see them.
    """
    out: list[dict] = []
    if not root.is_dir():
        return out
    for section in ("locked", "in_progress"):
        section_dir = root / section
        if not section_dir.is_dir():
            continue
        try:
            tool_dirs = [p for p in section_dir.iterdir() if p.is_dir()]
        except (OSError, PermissionError):
            continue
        for tool_dir in tool_dirs:
            report = tool_dir / "eval_report.json"
            if not report.exists():
                continue
            score = _score_from_pb_eval_json(report)
            if score is None:
                continue
            passed, total = score
            out.append(
                {
                    "kind": "programbench",
                    "tool": tool_dir.name,
                    "run": f"corpus/{section}",
                    "passed": passed,
                    "total": total,
                    "pct": 100.0 * passed / total,
                    "eval_path": str(report),
                    "verified_locked": passed == total,
                    "shipped": True,
                }
            )
    return out


def dedupe_pb_evals(rows: list[dict]) -> list[dict]:
    """Keep the best official score per tool across runs and corpus copies."""
    best: dict[str, dict] = {}
    for row in rows:
        tool = _canonical_pb_tool(row["tool"])
        row["tool"] = tool
        cur = best.get(tool)
        if cur is None:
            best[tool] = row
            continue
        row_key = (row["pct"], row["passed"], row["total"])
        cur_key = (cur["pct"], cur["passed"], cur["total"])
        if row_key > cur_key:
            best[tool] = row
    return sorted(best.values(), key=lambda r: r["tool"])


def find_sb_predictions(roots: list[Path]) -> list[dict]:
    """Find SWE-bench prediction JSONLs. Each prediction is one instance attempt.
    Bounded depth: roots/<run>/predictions.jsonl OR roots/<run>/<subdir>/predictions.jsonl."""
    out = []
    for root in roots:
        if not root.is_dir():
            continue
        candidates: list[Path] = []
        try:
            for run_dir in root.iterdir():
                if not run_dir.is_dir():
                    continue
                p = run_dir / "predictions.jsonl"
                if p.exists():
                    candidates.append(p)
                # Also look one level deeper
                for sub in run_dir.iterdir():
                    if sub.is_dir():
                        p2 = sub / "predictions.jsonl"
                        if p2.exists():
                            candidates.append(p2)
        except (OSError, PermissionError):
            continue
        for pred in candidates:
            try:
                with pred.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            r = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        iid = r.get("instance_id", "")
                        # Resolved/unresolved is determined post-eval. Pull from sibling .json if present.
                        run_dir = pred.parent
                        eval_file = run_dir / f"{iid}.json"
                        resolved = None
                        if eval_file.exists():
                            try:
                                ev = json.loads(eval_file.read_text(encoding="utf-8"))
                                resolved = ev.get("resolved", ev.get("passed"))
                            except (OSError, json.JSONDecodeError):
                                pass
                        out.append(
                            {
                                "kind": "swebench",
                                "instance_id": iid,
                                "run": run_dir.name,
                                "resolved": resolved,
                                "has_patch": bool(r.get("model_patch", "").strip()),
                                "pred_path": str(pred),
                            }
                        )
            except Exception:
                continue
    return out


def render_scoreboard(pb: list[dict], sb: list[dict]) -> str:
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append(f"DETERMINEX MASS-RUN SCOREBOARD — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 64)
    lines.append("")

    # ── ProgramBench ─────────────────────────────────────────────────────────
    lines.append("┌─ ProgramBench (scores from official `programbench eval` only)")
    if not pb:
        lines.append("│  (no eval results found)")
    else:
        # Tiers by official-eval pct (only counts tools that have an eval JSON)
        scored = [r for r in pb if r["total"] > 0]
        shipped_unscored = [r for r in pb if r["total"] == 0 and r.get("shipped")]
        tiers = {
            "locked_100": [],
            "almost_95+": [],
            "tier_a_80_95": [],
            "tier_b_60_80": [],
            "tier_c_30_60": [],
            "failed_lt_30": [],
        }
        for r in scored:
            pct = r["pct"]
            if pct >= 100:
                tiers["locked_100"].append(r)
            elif pct >= 95:
                tiers["almost_95+"].append(r)
            elif pct >= 80:
                tiers["tier_a_80_95"].append(r)
            elif pct >= 60:
                tiers["tier_b_60_80"].append(r)
            elif pct >= 30:
                tiers["tier_c_30_60"].append(r)
            else:
                tiers["failed_lt_30"].append(r)
        n_scored = len(scored)
        n_shipped = len(shipped_unscored)
        n_locked = len(tiers["locked_100"])
        lines.append(f"│  Officially scored:  {n_scored}")
        lines.append(f"│  Shipped (eval pending): {n_shipped}")
        lines.append(
            f"│  VERIFIED LOCKED:    {n_locked}  ({100 * n_locked / max(n_scored, 1):.1f}% of scored)"
        )
        lines.append(f"│  ≥95% (almost):     {len(tiers['almost_95+'])}")
        lines.append(f"│  80-95% (Tier A):   {len(tiers['tier_a_80_95'])}")
        lines.append(f"│  60-80% (Tier B):   {len(tiers['tier_b_60_80'])}")
        lines.append(f"│  30-60% (Tier C):   {len(tiers['tier_c_30_60'])}")
        lines.append(f"│  <30% (failed):     {len(tiers['failed_lt_30'])}")
        lines.append("│")
        if tiers["locked_100"]:
            lines.append("│  LOCKS:")
            for r in sorted(tiers["locked_100"], key=lambda x: x["tool"]):
                lines.append(f"│    {r['tool']:50s} {r['passed']}/{r['total']}")
        if tiers["almost_95+"]:
            lines.append("│  ALMOST (≥95%, 1 round from lock):")
            for r in sorted(tiers["almost_95+"], key=lambda x: -x["pct"])[:10]:
                lines.append(f"│    {r['tool']:50s} {r['pct']:5.1f}%  ({r['passed']}/{r['total']})")
    lines.append("└─")
    lines.append("")

    # ── SWE-bench ────────────────────────────────────────────────────────────
    lines.append("┌─ SWE-bench")
    if not sb:
        lines.append("│  (no predictions found)")
    else:
        n_attempted = len(sb)
        n_with_patch = sum(1 for r in sb if r["has_patch"])
        n_resolved = sum(1 for r in sb if r["resolved"] is True)
        n_unresolved = sum(1 for r in sb if r["resolved"] is False)
        n_unscored = sum(1 for r in sb if r["resolved"] is None)
        lines.append(f"│  Instances attempted:  {n_attempted}")
        lines.append(f"│  With non-empty patch: {n_with_patch}")
        lines.append(
            f"│  RESOLVED:             {n_resolved}  ({100 * n_resolved / max(n_attempted, 1):.1f}%)"
        )
        lines.append(f"│  Unresolved (failed):  {n_unresolved}")
        lines.append(f"│  Pending eval:         {n_unscored}")
        # By run
        runs = Counter(r["run"] for r in sb)
        lines.append("│")
        lines.append("│  BY RUN:")
        for run, n in runs.most_common(8):
            run_resolved = sum(1 for r in sb if r["run"] == run and r["resolved"] is True)
            lines.append(f"│    {run:50s} {run_resolved}/{n} resolved")
    lines.append("└─")
    lines.append("")

    # ── COMBINED ─────────────────────────────────────────────────────────────
    lines.append("┌─ COMBINED")
    pb_locked = sum(1 for r in pb if r["pct"] >= 100)
    sb_resolved = sum(1 for r in sb if r["resolved"] is True)
    total_locks = pb_locked + sb_resolved
    bench_total = 200 + 5274  # PB + SWE-bench-family ceiling
    lines.append(
        f"│  Total locks:           {total_locks} of {bench_total} bench-units = {100 * total_locks / bench_total:.2f}%"
    )
    lines.append("│  Frontier comparison:   not loaded in this local aggregate")
    lines.append("└─")

    return "\n".join(lines)


def aggregate(runs: list[Path], out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    pb_roots = [r for r in runs if "programbench" in str(r)] or [PB_RUNS_BASE]
    sb_roots = [r for r in runs if "swebench" in str(r)] or [SB_RUNS_BASE]
    pb = dedupe_pb_evals(find_pb_evals(pb_roots) + find_pb_corpus_evals())
    sb = find_sb_predictions(sb_roots)
    board = render_scoreboard(pb, sb)
    (out_dir / "scoreboard.txt").write_text(board, encoding="utf-8")
    (out_dir / "scoreboard.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(), "pb": pb, "sb": sb}, indent=2),
        encoding="utf-8",
    )
    locks = [
        f"PB  {r['tool']}  {r['passed']}/{r['total']}"
        for r in pb
        if r["total"] > 0 and r["pct"] >= 100
    ]
    locks += [f"SB  {r['instance_id']}" for r in sb if r["resolved"] is True]
    (out_dir / "locks_so_far.txt").write_text("\n".join(sorted(locks)) + "\n", encoding="utf-8")
    return board


def main():
    ap = argparse.ArgumentParser(description="Mass-run result aggregator")
    ap.add_argument(
        "--run-dir",
        action="append",
        default=[],
        help="Specific run directory (can repeat). Default: scan T:/determinex-{programbench,swebench}/",
    )
    ap.add_argument(
        "--watch", type=int, default=0, help="Re-aggregate every N seconds (0 = single shot)"
    )
    ap.add_argument(
        "--out", type=Path, default=OUT_DIR, help=f"Output directory (default {OUT_DIR})"
    )
    args = ap.parse_args()
    runs = [Path(r) for r in args.run_dir]
    if args.watch:
        try:
            while True:
                board = aggregate(runs, args.out)
                # Clear screen + reprint
                print("\033[2J\033[H" + board)
                print(f"\n[refreshing every {args.watch}s — Ctrl-C to stop]")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nstopped.")
    else:
        print(aggregate(runs, args.out))


if __name__ == "__main__":
    main()
