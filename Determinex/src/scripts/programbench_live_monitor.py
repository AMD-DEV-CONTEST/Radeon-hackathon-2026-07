"""scripts/programbench_live_monitor.py — the cockpit reader for ProgramBench runs.

Reads from the universal ledger (logs/determinex_ledger.db, backed by JSONL) and
renders the current state of one or more ProgramBench runs in three forms:

    --table     human-readable table (default)
    --json      JSON payload for the frontend / piping
    --watch     refresh every --interval seconds until --quiet-secs of no change

Surfaces (what the directive asked for):
    - run progress (N/M completed)
    - rolling average score
    - top failure families with counts + tools-affected
    - recommended next universal patch (deferred — calls the advisor if --advise)
    - artifacts list (paths to eval JSONs)

The JSON output IS the API contract for the future "Benchmark Lab" tab. Stable
keys, stable types. Add fields by extension only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_ledger import (  # type: ignore[import-not-found]
    SQLITE_PATH,
    _open_db,
    query_run_meta,
    rebuild_index,
)

LOCK_BOARD_PATH = Path(__file__).resolve().parents[1] / "logs" / "programbench_lock_board.json"


# ---------------------------------------------------------------------------
# Locked-tool drilldown — real per-tool evidence for the cockpit
# ---------------------------------------------------------------------------


def _repo_rel(path_str: str, repo_root: Path) -> str:
    """Normalize an absolute board path to a forward-slash repo-relative path."""
    if not path_str:
        return ""
    p = path_str.replace("\\", "/")
    root = str(repo_root).replace("\\", "/").rstrip("/") + "/"
    if p.lower().startswith(root.lower()):  # case-insensitive (Windows drive letters)
        p = p[len(root) :]
    return p


def load_locked_tools(board_path: Path = LOCK_BOARD_PATH) -> list[dict]:
    """Read the canonical ProgramBench lock board and return the archived locks.

    Source of truth: ``logs/programbench_lock_board.json`` (the board mirror of
    the ``corpus/programbench/locked/<tool>/`` filesystem-of-record). Only rows
    with ``locked_archive=True`` are surfaced — a strict lock is an archived eval
    at ``passed == runnable_total``. Returns ``[]`` if the board is missing or
    unreadable, so the cockpit degrades to header stats only (never invents rows).
    """
    try:
        rows = json.loads(board_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    repo_root = board_path.resolve().parents[1]
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("locked_archive"):
            continue
        name = (
            r.get("locked_dir_name")
            or r.get("locked_archive_slug")
            or str(r.get("base_slug") or "").split("__")[-1]
        )
        passed = r.get("locked_passed", r.get("best_passed"))
        runnable = r.get("locked_runnable_total", r.get("best_runnable_total"))
        score = r.get("locked_score", r.get("best_score"))
        evidence = _repo_rel(r.get("locked_eval_path") or r.get("best_eval_path") or "", repo_root)
        out.append(
            {
                "name": name,
                "score": score,
                "passed": passed,
                "runnable_total": runnable,
                "evidence_path": evidence,
            }
        )
    out.sort(key=lambda t: str(t["name"]).lower())
    return out


# ---------------------------------------------------------------------------
# Snapshot — the unit the frontend subscribes to
# ---------------------------------------------------------------------------


def snapshot(
    run_id: str,
    expected_total: int | None = None,
    sqlite_path: Path = SQLITE_PATH,
) -> dict:
    """Return a complete snapshot of one run as of right now.

    expected_total: known target task count (e.g. 115 for mass_run_v2). When
    provided, the snapshot includes progress %, ETA hints, and a 'complete' flag.
    """
    if not sqlite_path.exists():
        rebuild_index(sqlite_path)
    conn = _open_db(sqlite_path)
    try:
        # Per-task latest eval event
        rows = conn.execute(
            """SELECT task_id, score, failures_json, artifact, timestamp, extra_json
               FROM events
               WHERE run_id = ? AND phase = 'eval' AND status = 'completed'
               ORDER BY timestamp""",
            (run_id,),
        ).fetchall()
        run_row = conn.execute(
            "SELECT started_at, last_seen_at, n_events FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()

    tasks: list[dict] = []
    scores: list[float] = []
    family_totals: dict[str, int] = {}
    family_tool_set: dict[str, set] = {}
    total_passed = 0
    total_tests = 0

    for r in rows:
        task_id, score, failures_json, artifact, ts, extra_json = r
        extra = json.loads(extra_json) if extra_json else {}
        families = json.loads(failures_json) if failures_json else {}
        for fam, count in families.items():
            family_totals[fam] = family_totals.get(fam, 0) + int(count)
            family_tool_set.setdefault(fam, set()).add(task_id)
        if score is not None:
            scores.append(score)
        total_passed += extra.get("passed", 0)
        total_tests += extra.get("total", 0)
        tasks.append(
            {
                "task_id": task_id,
                "score": score,
                "passed": extra.get("passed"),
                "total": extra.get("total"),
                "top_family": max(families.items(), key=lambda kv: kv[1])[0] if families else None,
                "artifact": artifact,
                "timestamp": ts,
            }
        )

    n_completed = len(tasks)
    rolling_avg = round(sum(scores) / len(scores), 1) if scores else 0.0
    pct_tests = round(100 * total_passed / max(total_tests, 1), 1)

    families_ranked = sorted(
        (
            {"family": fam, "failures": cnt, "tools_affected": len(family_tool_set.get(fam, set()))}
            for fam, cnt in family_totals.items()
        ),
        key=lambda d: -d["failures"],
    )

    progress: dict[str, Any] = {}
    if expected_total:
        progress["expected_total"] = expected_total
        progress["pct_done"] = round(100 * n_completed / expected_total, 1)
        progress["complete"] = n_completed >= expected_total

    # Surface run provenance so every cockpit snapshot answers "which patch
    # produced these numbers" without needing a second query.
    meta = query_run_meta(run_id, sqlite_path=sqlite_path) or {}

    # Real per-tool drilldown: the archived ProgramBench locks (board mirror of
    # corpus/programbench/locked/). Independent of the SQLite run above.
    locked_tools = load_locked_tools()

    return {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "started_at": run_row[0] if run_row else None,
        "last_seen_at": run_row[1] if run_row else None,
        "n_events": run_row[2] if run_row else 0,
        "meta": meta,
        "n_completed_tasks": n_completed,
        "progress": progress,
        "rolling_avg_score": rolling_avg,
        "total_passed": total_passed,
        "total_tests": total_tests,
        "pct_tests_passing": pct_tests,
        "perfect_scores": sum(1 for t in tasks if (t.get("score") or 0) >= 99.9),
        "zero_scores": sum(1 for t in tasks if (t.get("score") or 0) == 0),
        "top_families": families_ranked[:15],
        "tasks_top": sorted(tasks, key=lambda t: -(t.get("score") or 0))[:10],
        "tasks_bottom": sorted(tasks, key=lambda t: t.get("score") or 0)[:10],
        "locked_tools": locked_tools,
        "locked_count": len(locked_tools),
    }


# ---------------------------------------------------------------------------
# Table renderer
# ---------------------------------------------------------------------------


def render_table(snap: dict) -> str:
    lines: list[str] = []
    lines.append(f"=== Run: {snap['run_id']} ===")
    m = snap.get("meta") or {}
    if m:
        v = m.get("scaffold_version") or "?"
        f = m.get("patch_family") or "?"
        b = m.get("base_run_id") or "—"
        g = (m.get("git_sha") or "?")[:12]
        d = " (dirty)" if m.get("git_dirty") else ""
        lines.append(f"  Provenance     scaffold={v}  family={f}  base={b}  git={g}{d}")
    if snap.get("progress"):
        p = snap["progress"]
        bar_w = 30
        filled = int(bar_w * p["pct_done"] / 100)
        bar = "█" * filled + "·" * (bar_w - filled)
        lines.append(
            f"  Progress       [{bar}]  {snap['n_completed_tasks']}/{p['expected_total']} ({p['pct_done']}%)"
        )
    else:
        lines.append(f"  Completed tasks: {snap['n_completed_tasks']}")
    lines.append(f"  Rolling avg    {snap['rolling_avg_score']:>5}/100")
    lines.append(
        f"  Tests passing  {snap['total_passed']:,} / {snap['total_tests']:,}  ({snap['pct_tests_passing']}%)"
    )
    lines.append(f"  Perfect scores {snap['perfect_scores']:>5}")
    lines.append(f"  Zero scores    {snap['zero_scores']:>5}")
    lines.append("")
    lines.append("  Top failure families (cross-batch):")
    lines.append(f"  {'rank':>4}  {'failures':>9}  {'tools':>5}  family")
    for i, f in enumerate(snap["top_families"][:10], 1):
        lines.append(f"  {i:>4}  {f['failures']:>9,}  {f['tools_affected']:>5}  {f['family']}")
    lines.append("")
    if snap.get("tasks_top"):
        lines.append("  Top 5 tools by score:")
        for t in snap["tasks_top"][:5]:
            lines.append(
                f"  {t.get('score', 0):>5}  {t.get('passed', 0):>4}/{t.get('total', 0):<5}  {t['task_id'][:60]}"
            )
        lines.append("")
        lines.append("  Bottom 5 tools by score:")
        for t in snap["tasks_bottom"][:5]:
            lines.append(
                f"  {t.get('score', 0):>5}  {t.get('passed', 0):>4}/{t.get('total', 0):<5}  {t['task_id'][:60]}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli():
    ap = argparse.ArgumentParser(description="ProgramBench live cockpit monitor")
    ap.add_argument("--run-id", default="mass_run_v2_base")
    ap.add_argument(
        "--expected-total",
        type=int,
        default=115,
        help="known target task count (drives progress bar)",
    )
    ap.add_argument("--json", action="store_true", help="emit JSON instead of table")
    ap.add_argument("--watch", action="store_true", help="refresh every --interval seconds")
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument(
        "--quiet-secs",
        type=float,
        default=600.0,
        help="exit after this many seconds with no change (watch only)",
    )
    ap.add_argument(
        "--advise",
        action="store_true",
        help="also run scripts/programbench_patch_advisor.py and surface its top patch",
    )
    args = ap.parse_args()

    def render_once() -> tuple[dict, str]:
        snap = snapshot(args.run_id, expected_total=args.expected_total)
        if args.advise:
            try:
                from programbench_patch_advisor import propose_top_patch  # type: ignore

                snap["recommended_patch"] = propose_top_patch(snap)
            except ImportError:
                snap["recommended_patch"] = {"status": "advisor_unavailable"}
        if args.json:
            return snap, json.dumps(snap, indent=2, default=str)
        return snap, render_table(snap)

    if not args.watch:
        snap, out = render_once()
        print(out)
        return

    last_n = -1
    last_change = time.time()
    while True:
        snap, out = render_once()
        if snap["n_completed_tasks"] != last_n:
            print("\033[2J\033[H" if not args.json else "", end="")  # clear screen in table mode
            print(out, flush=True)
            last_n = snap["n_completed_tasks"]
            last_change = time.time()
        if (snap.get("progress") or {}).get("complete"):
            print("\n=== RUN COMPLETE ===", flush=True)
            return
        if time.time() - last_change > args.quiet_secs:
            print(f"\n=== quiet for {args.quiet_secs}s — exiting watch ===", flush=True)
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    _cli()
