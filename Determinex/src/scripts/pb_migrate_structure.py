"""
pb_migrate_structure.py — One-time migration from flat locked/ to tiered structure.

Reads all locked/ dirs, classifies each, and:
  - Creates pending_unlock/{priority}/  entries with unlock_ticket.json
  - Creates ceiling_confirmed/ entries with ceiling_analysis.json
  - Leaves strict locks and upstream-skips in place (they will move to tiers
    on next pb_build_index.py --migrate run, or on first promotion)

Does NOT move strict/upstream locks yet (per spec: validate first).
"""

from __future__ import annotations

import collections
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
PB_DIR = ROOT / "corpus" / "programbench"
LOCKED_BASE = PB_DIR / "locked"
PENDING_BASE = PB_DIR / "pending_unlock"
CEILING_BASE = PB_DIR / "ceiling_confirmed"
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"

# Ceiling-confirmed tools (structural impossibles from CLAUDE.md)
CEILING_TOOLS = {
    "amber": {
        "canonical_slug": "dalance__amber",
        "reason": "Contradictory rc=0/rc=1 assertions between branches for identical invocations. Camp A asserts rc=1 on no-TTY pipe; Camp B asserts rc=0+file-modify for same invocation. No single binary satisfies both.",
        "true_ceiling_pct": 97.8,
        "ceiling_passed": 587,
        "ceiling_total": 600,
    },
    "hexyl": {
        "canonical_slug": "sharkdp__hexyl",
        "reason": "--panels=1 produces 8 bytes/row; tests asserting 1 row for 16 bytes are impossible without breaking golden snapshot test. Decimal/octal zero-pad means \\b10\\b regex won't match 010.",
        "true_ceiling_pct": 99.37,
        "ceiling_passed": 940,
        "ceiling_total": 946,
    },
    "fd": {
        "canonical_slug": "sharkdp__fd",
        "reason": "Root user in container makes all files executable defeating chmod; Python subprocess raises FileNotFoundError on deleted cwd; \\\\Ac is literal not anchor in Rust regex.",
        "true_ceiling_pct": 99.37,
        "ceiling_passed": 1263,
        "ceiling_total": 1271,
    },
    "johanneskaufmann__html-to-markdown": {
        "canonical_slug": "johanneskaufmann__html-to-markdown",
        "reason": "Three branches assert conflicting --version strings ('2.3.4-test' vs 'dev/unknown') for identical invocations. 4 independent evals all land at 971/974.",
        "true_ceiling_pct": 99.69,
        "ceiling_passed": 971,
        "ceiling_total": 974,
    },
    "doxygen": {
        "canonical_slug": "doxygen__doxygen",
        "reason": "tests.json for 2 of 3 branches has duplicate test IDs with both eval.tests. and tests. prefixes from inconsistent eval/__init__.py presence during test generation. JUnit XML only ever outputs one prefix — the other half is always not_run. Irreconcilable via compile.sh changes.",
        "true_ceiling_pct": 63.6,
        "ceiling_passed": 250,
        "ceiling_total": 394,
    },
    "richgo": {
        "canonical_slug": "kyoh86__richgo",
        "reason": "36 tests in tests.json have @go_test suffix (e.g., test_wrapper_mode_passing_test@go_test). Each has a passing non-@go_test counterpart but the @go_test variant is never in JUnit XML — structurally irreconcilable ceiling at ~787/823 = 95.6%.",
        "true_ceiling_pct": 95.6,
        "ceiling_passed": 787,
        "ceiling_total": 823,
    },
    "gping": {
        "canonical_slug": "orf__gping",
        "reason": "2 irreconcilable ping-missing ENXIO failures (gping doesn't fall back to ping binary for ENXIO error code) + 4 upstream pytest.mark.skip tests. Best achievable: 649/655 = 99.1%. Cannot satisfy passed==total.",
        "true_ceiling_pct": 99.08,
        "ceiling_passed": 649,
        "ceiling_total": 655,
    },
}

# Not-run priority thresholds
PRI1_THRESHOLD = 100
PRI2_THRESHOLD = 300


def load_eval_report(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def classify_eval(path: Path) -> dict:
    data = load_eval_report(path)
    if data is None:
        return {}
    tr = data.get("test_results", [])
    ctr = collections.Counter(r.get("status") for r in tr)
    total = len(tr)
    passed = ctr.get("passed", 0)
    not_run = ctr.get("not_run", 0)
    skipped = ctr.get("skipped", 0)
    failed = ctr.get("failure", 0) + ctr.get("failed", 0)
    pct = passed / total * 100 if total else 0

    if passed == total and not_run == 0 and failed == 0 and skipped == 0:
        status = "strict_lock"
    elif passed + skipped == total and not_run == 0 and failed == 0:
        status = "upstream_skips"
    elif not_run > 0:
        status = "pending_unlock"
    else:
        status = "partial"

    return dict(
        status=status,
        passed=passed,
        total=total,
        not_run=not_run,
        skipped=skipped,
        failed=failed,
        pct=pct,
    )


def detect_cap_type(tarball: Path) -> tuple[str, str | None]:
    """Returns (cap_type, cap_line) from the tarball's compile.sh."""
    import re
    import tarfile

    cap_pattern = re.compile(r"(del\s+items\s*\[\s*\d+\s*:\s*\])")
    collect_ignore = re.compile(r"collect_ignore_glob")

    has_cap = False
    has_ignore = False
    cap_line = None

    if not tarball.exists():
        return "none", None

    try:
        with tarfile.open(tarball, "r:gz") as tf:
            for m in tf.getmembers():
                if "compile.sh" in m.name or "conftest.py" in m.name:
                    f = tf.extractfile(m)
                    if f is None:
                        continue
                    content = f.read().decode("utf-8", errors="replace")
                    m_cap = cap_pattern.search(content)
                    if m_cap:
                        has_cap = True
                        cap_line = m_cap.group(0)
                    if collect_ignore.search(content):
                        has_ignore = True
    except Exception:
        pass

    if has_cap and has_ignore:
        return "both", cap_line
    if has_cap:
        return "del_items_400", cap_line
    if has_ignore:
        return "collect_ignore_glob", cap_line
    return "none", cap_line


def create_unlock_ticket(slug: str, tool_dir: Path, counts: dict, dest_dir: Path) -> None:
    tarball = tool_dir / "submission.tar.gz"
    cap_type, cap_line = detect_cap_type(tarball)

    ticket = {
        "slug": slug,
        "current_passed": counts["passed"],
        "current_total": counts["total"],
        "current_not_run": counts["not_run"],
        "current_skipped": counts.get("skipped", 0),
        "current_failed": counts.get("failed", 0),
        "cap_type": cap_type,
        "cap_line": cap_line or "del items[400:]",
        "estimated_uncapped_total": counts["total"],
        "priority": (
            1
            if counts["not_run"] < PRI1_THRESHOLD
            else 2
            if counts["not_run"] < PRI2_THRESHOLD
            else 3
        ),
        "assigned_to": "unassigned",
        "created_at": datetime.now(UTC).isoformat(),
        "last_attempt": None,
        "attempts": 0,
        "status": "pending",
    }

    (dest_dir / "unlock_ticket.json").write_text(json.dumps(ticket, indent=2), encoding="utf-8")


def create_ceiling_analysis(slug: str, info: dict, tool_dir: Path, dest_dir: Path) -> None:
    # Copy best eval report if exists
    report = tool_dir / "eval_report.json"
    if report.exists():
        shutil.copy2(report, dest_dir / "best_eval_report.json")

    analysis = {
        "slug": slug,
        "canonical_slug": info.get("canonical_slug", slug),
        "reason": info.get("reason", "Ceiling confirmed — see CLAUDE.md"),
        "true_ceiling_pct": info.get("true_ceiling_pct"),
        "ceiling_passed": info.get("ceiling_passed"),
        "ceiling_total": info.get("ceiling_total"),
        "confirmed_at": datetime.now(UTC).isoformat(),
        "confirmed_by": "manual analysis",
        "do_not_retry": True,
    }
    (dest_dir / "ceiling_analysis.json").write_text(
        json.dumps(analysis, indent=2), encoding="utf-8"
    )


def main():
    skip_dirs = {"tier_1_perfect", "tier_2_upstream_skips"}
    counts_by_status: dict[str, list] = collections.defaultdict(list)

    print("Scanning locked/ directory...")
    for tool_dir in sorted(LOCKED_BASE.iterdir()):
        if not tool_dir.is_dir() or tool_dir.name in skip_dirs:
            continue

        slug = tool_dir.name
        report = tool_dir / "eval_report.json"
        counts = classify_eval(report)

        if not counts:
            print(f"  SKIP (no eval_report): {slug}")
            continue

        # Check if ceiling-confirmed
        is_ceiling = any(slug == k or slug.endswith(k) or k in slug for k in CEILING_TOOLS)
        ceiling_key = next(
            (k for k in CEILING_TOOLS if slug == k or slug.endswith(k) or k in slug), None
        )

        status = counts["status"]
        counts_by_status[status].append(slug)

        if status == "strict_lock":
            print(f"  ✓ STRICT LOCK:    {slug} ({counts['passed']}/{counts['total']})")
            # Leave in place — migration to tier dir happens separately
            continue

        if status == "upstream_skips":
            print(
                f"  ⚡ UPSTREAM SKIP:  {slug} ({counts['passed']}/{counts['total']}, sk={counts['skipped']})"
            )
            continue

        if is_ceiling and ceiling_key:
            # Move to ceiling_confirmed
            dest = CEILING_BASE / slug
            dest.mkdir(parents=True, exist_ok=True)
            create_ceiling_analysis(slug, CEILING_TOOLS[ceiling_key], tool_dir, dest)
            print(f"  ⛔ CEILING:        {slug} → ceiling_confirmed/")
            continue

        if status == "pending_unlock":
            nr = counts["not_run"]
            pri = 1 if nr < PRI1_THRESHOLD else 2 if nr < PRI2_THRESHOLD else 3
            pri_dir_name = f"priority_{pri}_under{PRI1_THRESHOLD if pri == 1 else PRI2_THRESHOLD if pri == 2 else 'max'}"
            # Fix dir name
            if pri == 3:
                pri_dir_name = "priority_3_over300"
            dest = PENDING_BASE / pri_dir_name / slug
            dest.mkdir(parents=True, exist_ok=True)

            # Copy eval_report and submission
            for fname in ("eval_report.json", "submission.tar.gz", "lessons.md"):
                src = tool_dir / fname
                if src.exists():
                    shutil.copy2(src, dest / fname)

            # Copy source dir if exists
            src_dir = tool_dir / "source"
            if src_dir.exists() and not (dest / "source").exists():
                shutil.copytree(src_dir, dest / "source")

            create_unlock_ticket(slug, tool_dir, counts, dest)
            print(f"  ⏳ PENDING P{pri}:    {slug} (nr={nr}) → priority_{pri}/")
            continue

        print(f"  ❓ OTHER:          {slug} {counts}")

    print()
    print("=== MIGRATION SUMMARY ===")
    for status, tools in sorted(counts_by_status.items()):
        print(f"  {status}: {len(tools)}")
        for t in tools[:5]:
            print(f"    - {t}")
        if len(tools) > 5:
            print(f"    ... ({len(tools) - 5} more)")

    # Also write ceiling_confirmed for tools NOT in locked/ (board-only)
    print("\nCreating ceiling_confirmed entries for non-locked ceiling tools...")
    board = {}
    if BOARD_JSON.exists():
        try:
            bl = json.loads(BOARD_JSON.read_text(encoding="utf-8", errors="replace"))
            board = {e["base_slug"]: e for e in bl}
        except Exception:
            pass

    for key, info in CEILING_TOOLS.items():
        canonical = info.get("canonical_slug", key)
        dest = CEILING_BASE / canonical
        if dest.exists():
            continue  # Already created above
        # Check if it's in locked
        locked_path = LOCKED_BASE / canonical
        if locked_path.exists():
            continue  # Handled above

        dest.mkdir(parents=True, exist_ok=True)
        board_entry = board.get(canonical, {})
        # Create a minimal ceiling analysis
        analysis = {
            "slug": canonical,
            "reason": info.get("reason", ""),
            "true_ceiling_pct": info.get("true_ceiling_pct"),
            "ceiling_passed": info.get("ceiling_passed"),
            "ceiling_total": info.get("ceiling_total"),
            "best_passed": board_entry.get("best_passed", info.get("ceiling_passed")),
            "best_total": board_entry.get("best_total", info.get("ceiling_total")),
            "confirmed_at": datetime.now(UTC).isoformat(),
            "do_not_retry": True,
        }
        (dest / "ceiling_analysis.json").write_text(
            json.dumps(analysis, indent=2), encoding="utf-8"
        )
        print(f"  ⛔ Created: ceiling_confirmed/{canonical}/")

    print("\nMigration complete.")
    print("Next: python scripts/pb_build_index.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
