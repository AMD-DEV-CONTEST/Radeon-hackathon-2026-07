"""
pb_build_index.py — Build eval_index.json from filesystem scan.

Sources (in priority order):
  1. corpus/programbench/locked/tier_1_perfect/  → strict_lock
  2. corpus/programbench/locked/tier_2_upstream_skips/ → upstream_skips
  3. corpus/programbench/locked/ (flat legacy dirs) → classify by eval_report
  4. corpus/programbench/pending_unlock/ → pending_unlock
  5. corpus/programbench/ceiling_confirmed/ → ceiling_confirmed
  6. corpus/programbench/in_progress/ → in_progress
  7. logs/programbench_lock_board.json → board_cache_only (fallback)

Outputs: corpus/programbench/eval_index.json
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PB_DIR = ROOT / "corpus" / "programbench"
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"
INDEX_OUT = PB_DIR / "eval_index.json"

LOCKED_BASE = PB_DIR / "locked"
TIER1 = LOCKED_BASE / "tier_1_perfect"
TIER2 = LOCKED_BASE / "tier_2_upstream_skips"
PENDING = PB_DIR / "pending_unlock"
CEILING = PB_DIR / "ceiling_confirmed"
IN_PROGRESS = PB_DIR / "in_progress"


def load_eval_report(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def classify_eval_report(data: dict) -> dict:
    """Return counts from eval_report test_results."""
    tr = data.get("test_results", [])
    ctr = collections.Counter(r.get("status") for r in tr)
    total = len(tr)
    passed = ctr.get("passed", 0)
    not_run = ctr.get("not_run", 0)
    skipped = ctr.get("skipped", 0)
    failed = ctr.get("failure", 0) + ctr.get("failed", 0)
    pct = (passed / total * 100) if total else 0.0
    return dict(
        total=total, passed=passed, not_run=not_run, skipped=skipped, failed=failed, pct=pct
    )


def determine_status(counts: dict) -> str:
    p, t = counts["passed"], counts["total"]
    nr, sk, fa = counts["not_run"], counts["skipped"], counts["failed"]
    if p == t and nr == 0 and fa == 0 and sk == 0:
        return "strict_lock"
    if p + sk == t and nr == 0 and fa == 0:
        return "upstream_skips"
    if nr > 0:
        return "pending_unlock"
    if fa > 0:
        return "partial"
    return "partial"


def determine_tier(status: str) -> str:
    if status == "strict_lock":
        return "tier_1_perfect"
    if status == "upstream_skips":
        return "tier_2_upstream_skips"
    return ""


def scan_tier_dir(tier_dir: Path, status_override: str) -> list[dict]:
    entries = []
    if not tier_dir.exists():
        return entries
    for tool_dir in sorted(tier_dir.iterdir()):
        if not tool_dir.is_dir():
            continue
        slug = tool_dir.name

        # Check for lock_metadata.json first (authoritative)
        meta_path = tool_dir / "lock_metadata.json"
        report_path = tool_dir / "eval_report.json"
        data = load_eval_report(report_path)

        if data is None:
            # No eval report — skip but note
            continue

        counts = classify_eval_report(data)
        status = status_override
        tier = determine_tier(status)

        entry = {
            "slug": slug,
            "status": status,
            "tier": tier,
            "official_score_pct": round(counts["pct"], 4),
            "official_passed": counts["passed"],
            "official_total": counts["total"],
            "official_not_run": counts["not_run"],
            "official_skipped": counts["skipped"],
            "official_failed": counts["failed"],
            "priority": None,
            "assigned_to": None,
            "source": "filesystem",
            "eval_report_path": str(report_path),
        }

        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                entry["locked_at"] = meta.get("locked_at")
                entry["language"] = meta.get("language")
                entry["eval_count"] = meta.get("eval_count")
            except Exception:
                pass

        entries.append(entry)
    return entries


def scan_locked_legacy(locked_base: Path, already_seen: set[str]) -> list[dict]:
    """Scan flat locked/ dirs (legacy layout before tier migration)."""
    entries = []
    skip_dirs = {"tier_1_perfect", "tier_2_upstream_skips"}
    if not locked_base.exists():
        return entries
    seen_short = {_tool_short_name(s) for s in already_seen}

    for tool_dir in sorted(locked_base.iterdir()):
        if not tool_dir.is_dir():
            continue
        if tool_dir.name in skip_dirs:
            continue
        slug = tool_dir.name
        short = _tool_short_name(slug)
        if slug in already_seen or short in seen_short:
            continue

        report_path = tool_dir / "eval_report.json"
        data = load_eval_report(report_path)
        if data is None:
            continue

        counts = classify_eval_report(data)
        status = determine_status(counts)
        tier = determine_tier(status)

        entry = {
            "slug": slug,
            "status": status,
            "tier": tier,
            "official_score_pct": round(counts["pct"], 4),
            "official_passed": counts["passed"],
            "official_total": counts["total"],
            "official_not_run": counts["not_run"],
            "official_skipped": counts["skipped"],
            "official_failed": counts["failed"],
            "priority": None,
            "assigned_to": None,
            "source": "filesystem_legacy",
            "eval_report_path": str(report_path),
        }
        entries.append(entry)
    return entries


def scan_pending_unlock(pending_base: Path, already_seen: set[str]) -> list[dict]:
    entries = []
    if not pending_base.exists():
        return entries

    priority_dirs = {
        "priority_1_under100": 1,
        "priority_2_under300": 2,
        "priority_3_over300": 3,
    }

    for pri_dirname, pri_num in priority_dirs.items():
        pri_dir = pending_base / pri_dirname
        if not pri_dir.exists():
            continue
        for tool_dir in sorted(pri_dir.iterdir()):
            if not tool_dir.is_dir():
                continue
            slug = tool_dir.name
            if slug in already_seen:
                continue

            ticket_path = tool_dir / "unlock_ticket.json"
            report_path = tool_dir / "eval_report.json"
            data = load_eval_report(report_path)

            ticket = {}
            if ticket_path.exists():
                try:
                    ticket = json.loads(ticket_path.read_text())
                except Exception:
                    pass

            counts = (
                classify_eval_report(data)
                if data
                else {
                    "total": ticket.get("current_total", 0),
                    "passed": ticket.get("current_passed", 0),
                    "not_run": ticket.get("current_not_run", 0),
                    "skipped": 0,
                    "failed": 0,
                    "pct": (ticket.get("current_passed", 0) / ticket.get("current_total", 1) * 100)
                    if ticket.get("current_total")
                    else 0,
                }
            )

            entry = {
                "slug": slug,
                "status": "pending_unlock",
                "tier": "",
                "official_score_pct": round(counts["pct"], 4),
                "official_passed": counts["passed"],
                "official_total": counts["total"],
                "official_not_run": counts["not_run"],
                "official_skipped": counts["skipped"],
                "official_failed": counts["failed"],
                "priority": pri_num,
                "assigned_to": ticket.get("assigned_to", "unassigned"),
                "source": "pending_unlock",
                "eval_report_path": str(report_path) if report_path.exists() else None,
                "unlock_ticket": ticket,
            }
            entries.append(entry)
            already_seen.add(slug)

    return entries


def scan_ceiling_confirmed(ceiling_base: Path, already_seen: set[str]) -> list[dict]:
    entries = []
    if not ceiling_base.exists():
        return entries
    seen_short = {_tool_short_name(s) for s in already_seen}
    for tool_dir in sorted(ceiling_base.iterdir()):
        if not tool_dir.is_dir():
            continue
        slug = tool_dir.name
        short = _tool_short_name(slug)
        if slug in already_seen or short in seen_short:
            continue

        analysis_path = tool_dir / "ceiling_analysis.json"
        report_path = tool_dir / "best_eval_report.json"
        data = load_eval_report(report_path)

        analysis = {}
        if analysis_path.exists():
            try:
                analysis = json.loads(analysis_path.read_text())
            except Exception:
                pass

        counts = (
            classify_eval_report(data)
            if data
            else {
                "total": analysis.get("best_total", 0),
                "passed": analysis.get("best_passed", 0),
                "not_run": 0,
                "skipped": 0,
                "failed": 0,
                "pct": (analysis.get("best_passed", 0) / analysis.get("best_total", 1) * 100)
                if analysis.get("best_total")
                else 0,
            }
        )

        entry = {
            "slug": slug,
            "status": "ceiling_confirmed",
            "tier": "",
            "official_score_pct": round(counts["pct"], 4),
            "official_passed": counts["passed"],
            "official_total": counts["total"],
            "official_not_run": counts["not_run"],
            "official_skipped": counts["skipped"],
            "official_failed": counts["failed"],
            "priority": None,
            "assigned_to": None,
            "source": "ceiling_confirmed",
            "ceiling_reason": analysis.get("reason", ""),
            "true_ceiling_pct": analysis.get("true_ceiling_pct"),
        }
        entries.append(entry)
        already_seen.add(slug)
    return entries


def scan_in_progress(ip_base: Path, already_seen: set[str]) -> list[dict]:
    entries = []
    if not ip_base.exists():
        return entries
    for tool_dir in sorted(ip_base.iterdir()):
        if not tool_dir.is_dir():
            continue
        slug = tool_dir.name
        if slug in already_seen:
            continue
        report_path = tool_dir / "current_eval.json"
        data = load_eval_report(report_path)
        counts = (
            classify_eval_report(data)
            if data
            else {
                "total": 0,
                "passed": 0,
                "not_run": 0,
                "skipped": 0,
                "failed": 0,
                "pct": 0.0,
            }
        )
        entry = {
            "slug": slug,
            "status": "in_progress",
            "tier": "",
            "official_score_pct": round(counts["pct"], 4),
            "official_passed": counts["passed"],
            "official_total": counts["total"],
            "official_not_run": counts["not_run"],
            "official_skipped": counts["skipped"],
            "official_failed": counts["failed"],
            "priority": None,
            "assigned_to": "local",
            "source": "in_progress",
        }
        entries.append(entry)
        already_seen.add(slug)
    return entries


def _tool_short_name(slug: str) -> str:
    """Extract short tool name from board slug like 'rcoh__angle-grinder' -> 'angle-grinder'."""
    if "__" in slug:
        return slug.split("__", 1)[1].split(".")[0]
    return slug.split(".")[0]


def load_board_fallback(board_path: Path, already_seen: set[str]) -> list[dict]:
    """Fallback: tools in the board JSON but not yet in the folder structure."""
    if not board_path.exists():
        return []
    try:
        board = json.loads(board_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []

    # Build a set of short tool names from already_seen for cross-reference
    seen_short = {_tool_short_name(s) for s in already_seen}

    entries = []
    for e in board:
        slug = e.get("base_slug", "")
        if not slug:
            continue
        short = _tool_short_name(slug)
        # Skip if we've already seen this tool under any name
        if slug in already_seen or short in seen_short:
            continue

        best_p = e.get("best_passed", 0) or 0
        best_t = e.get("best_total", 0) or 0
        pct = (best_p / best_t * 100) if best_t else 0.0

        entry = {
            "slug": slug,
            "status": "board_cache_only",
            "tier": "",
            "official_score_pct": round(pct, 4),
            "official_passed": best_p,
            "official_total": best_t,
            "official_not_run": e.get("not_run") or 0,
            "official_skipped": 0,
            "official_failed": 0,
            "priority": None,
            "assigned_to": "unassigned",
            "source": "board_cache",
            "next_action": e.get("next_action", ""),
            "eval_count": e.get("eval_count", 0),
        }
        entries.append(entry)
        already_seen.add(slug)
    return entries


def print_leaderboard(index: list[dict]) -> None:
    print()
    print("=" * 85)
    print(" DETERMINEX PROGRAMBENCH — EVAL INDEX")
    print("=" * 85)

    status_counts = collections.Counter(e["status"] for e in index)
    strict = status_counts.get("strict_lock", 0)
    upstream = status_counts.get("upstream_skips", 0)
    pending = status_counts.get("pending_unlock", 0)
    ceiling = status_counts.get("ceiling_confirmed", 0)
    board_only = status_counts.get("board_cache_only", 0)
    in_prog = status_counts.get("in_progress", 0)

    print(f"\n Strict locks (T1):    {strict:3d}  |  Upstream-skip (T2): {upstream:3d}")
    print(f" Pending unlock:       {pending:3d}  |  Ceiling confirmed:  {ceiling:3d}")
    print(f" In progress:          {in_prog:3d}  |  Board-cache only:   {board_only:3d}")
    print(f" Total:                {len(index):3d}")
    print()

    STATUS_ICON = {
        "strict_lock": "🔒 T1",
        "upstream_skips": "⚡ T2",
        "pending_unlock": "⏳ PND",
        "ceiling_confirmed": "⛔ CEIL",
        "in_progress": "🔧 WIP",
        "board_cache_only": "📋 BORD",
        "partial": "🔸 PART",
    }

    from rich.console import Console
    from rich.table import Table

    # STATUS_ICON's emoji crash on Windows consoles whose codepage isn't
    # UTF-8 (cp1252 etc.) -- both plain print() and rich hit the same
    # UnicodeEncodeError there (pre-existing, not new; just never surfaced
    # because most runs happen in a UTF-8-capable terminal). Reconfigure
    # rather than assume the environment is already UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    table = Table(show_edge=False, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Tool")
    table.add_column("Score", justify="right")
    table.add_column("P/T", justify="right")
    table.add_column("NR", justify="right")
    table.add_column("Status")
    for i, e in enumerate(index[:40], 1):
        slug = e["slug"][:38]
        pct = e["official_score_pct"]
        p = e["official_passed"]
        t = e["official_total"]
        nr = e["official_not_run"]
        icon = STATUS_ICON.get(e["status"], e["status"])
        pt = f"{p}/{t}" if t else "—"
        table.add_row(str(i), slug, f"{pct:.1f}%", pt, str(nr), icon)
    Console().print(table)

    if len(index) > 40:
        print(f"  ... ({len(index) - 40} more tools)")

    print()
    print(f" Strict lock rate: {strict}/{len(index)} = {strict / len(index) * 100:.1f}%")
    print(f" Potential locks after uncap: {strict + upstream + pending} (if all pending pass)")
    print("=" * 85)


def build_index(print_board: bool = True) -> list[dict]:
    seen: set[str] = set()
    index: list[dict] = []

    # 1. Tier-1 perfect locks
    t1 = scan_tier_dir(TIER1, "strict_lock")
    index.extend(t1)
    seen.update(e["slug"] for e in t1)

    # 2. Tier-2 upstream-skip locks
    t2 = scan_tier_dir(TIER2, "upstream_skips")
    index.extend(t2)
    seen.update(e["slug"] for e in t2)

    # 3. Ceiling confirmed — must run before legacy scan so ceiling tools aren't
    #    claimed as pending_unlock from their legacy locked/ flat dirs
    ceil_entries = scan_ceiling_confirmed(CEILING, seen)
    index.extend(ceil_entries)
    seen.update(e["slug"] for e in ceil_entries)

    # 4. Legacy flat locked/ dirs (classify each); ceiling tools already in seen
    legacy = scan_locked_legacy(LOCKED_BASE, seen)
    index.extend(legacy)
    seen.update(e["slug"] for e in legacy)

    # 5. Pending unlock
    pending = scan_pending_unlock(PENDING, seen)
    index.extend(pending)
    seen.update(e["slug"] for e in pending)

    # 6. In progress
    ip = scan_in_progress(IN_PROGRESS, seen)
    index.extend(ip)
    seen.update(e["slug"] for e in ip)

    # 7. Board fallback for anything not yet in folder structure
    fallback = load_board_fallback(BOARD_JSON, seen)
    index.extend(fallback)
    seen.update(e["slug"] for e in fallback)

    # Sort: strict/upstream locks first (score 100), then by score desc
    def sort_key(e):
        status_order = {
            "strict_lock": 0,
            "upstream_skips": 1,
            "pending_unlock": 2,
            "ceiling_confirmed": 3,
            "in_progress": 4,
            "partial": 5,
            "board_cache_only": 6,
        }
        return (status_order.get(e["status"], 99), -e["official_score_pct"])

    index.sort(key=sort_key)

    INDEX_OUT.parent.mkdir(parents=True, exist_ok=True)
    INDEX_OUT.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    if print_board:
        print_leaderboard(index)

    return index


def main():
    parser = argparse.ArgumentParser(description="Build ProgramBench eval index")
    parser.add_argument(
        "--print-leaderboard", action="store_true", help="Print full leaderboard to stdout"
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    index = build_index(print_board=not args.quiet or args.print_leaderboard)

    strict = sum(1 for e in index if e["status"] == "strict_lock")
    print(f"\nIndex written to: {INDEX_OUT}")
    print(f"Total tools: {len(index)} | Strict locks: {strict}/200")
    return 0


if __name__ == "__main__":
    sys.exit(main())
