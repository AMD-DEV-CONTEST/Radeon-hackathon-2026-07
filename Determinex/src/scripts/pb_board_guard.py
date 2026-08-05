#!/usr/bin/env python3
"""ProgramBench board guard — hard invariant checker for eval_index.json.

Usage:
    python scripts/pb_board_guard.py              # check only, print violations
    python scripts/pb_board_guard.py --guard       # exit code 1 if any violations
    python scripts/pb_board_guard.py --verbose     # print all entries checked
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "corpus" / "programbench" / "eval_index.json"

INVARIANTS = [
    # (name, condition_fn, message_fn)
    (
        "strict_lock_passed_eq_total",
        lambda e: (
            not (
                e.get("status") == "strict_lock"
                and e.get("official_passed") != e.get("official_total")
            )
        ),
        lambda e: (
            f"strict_lock but passed({e.get('official_passed')}) != total({e.get('official_total')})"
        ),
    ),
    (
        "strict_lock_not_run_zero",
        lambda e: not (e.get("status") == "strict_lock" and (e.get("official_not_run") or 0) != 0),
        lambda e: f"strict_lock but not_run={e.get('official_not_run')}",
    ),
    (
        "strict_lock_skipped_zero",
        lambda e: not (e.get("status") == "strict_lock" and (e.get("official_skipped") or 0) != 0),
        lambda e: f"strict_lock but skipped={e.get('official_skipped')}",
    ),
    (
        "strict_lock_failed_zero",
        lambda e: not (e.get("status") == "strict_lock" and (e.get("official_failed") or 0) != 0),
        lambda e: f"strict_lock but failed={e.get('official_failed')}",
    ),
    (
        "strict_lock_ofr_true",
        lambda e: (
            not (
                e.get("status") == "strict_lock"
                and e.get("official_full_suite_resolved") is not True
            )
        ),
        lambda e: (
            f"strict_lock but official_full_suite_resolved={e.get('official_full_suite_resolved')}"
        ),
    ),
    (
        "strict_lock_no_override",
        lambda e: True,  # checked separately via pb_override_scan.py
        lambda e: "",
    ),
    (
        "ofr_true_implies_strict_lock",
        lambda e: (
            not (
                e.get("official_full_suite_resolved") is True
                and e.get("status") not in ("strict_lock",)
                and not e.get("canonical_slug")
            )
        ),
        lambda e: (
            f"official_full_suite_resolved=True but status={e.get('status')} (not a canonical_slug alias)"
        ),
    ),
    (
        "score_pct_consistent",
        lambda e: (
            not (
                e.get("status") == "strict_lock"
                and e.get("official_passed") is not None
                and e.get("official_total") is not None
                and e.get("official_total") > 0
                and e.get("official_score_pct") is not None
                and abs(e["official_score_pct"] - 100.0) > 0.01
            )
        ),
        lambda e: (
            f"strict_lock but official_score_pct={e.get('official_score_pct')} (expected 100.0)"
        ),
    ),
    (
        "upstream_skips_has_skips",
        lambda e: (
            not (
                e.get("status") == "upstream_skips"
                and (e.get("official_skipped") or 0) == 0
                and (e.get("official_not_run") or 0) == 0
            )
        ),
        lambda e: "upstream_skips status but skipped=0 and not_run=0",
    ),
    (
        "ceiling_confirmed_has_reason",
        lambda e: not (e.get("status") == "ceiling_confirmed" and not e.get("ceiling_reason")),
        lambda e: "ceiling_confirmed but no ceiling_reason",
    ),
]


def check(index: list, verbose: bool = False) -> list[dict]:
    violations = []
    for entry in index:
        slug = entry.get("slug", "?")
        # Skip non-authoritative alias entries
        if entry.get("canonical_slug"):
            if verbose:
                print(f"  SKIP (alias) {slug}")
            continue
        entry_violations = []
        for inv_name, check_fn, msg_fn in INVARIANTS:
            if not check_fn(entry):
                entry_violations.append({"invariant": inv_name, "message": msg_fn(entry)})
        if entry_violations:
            violations.append({"slug": slug, "violations": entry_violations})
            for v in entry_violations:
                print(f"VIOLATION [{slug}] {v['invariant']}: {v['message']}")
        elif verbose:
            print(f"  OK {slug} ({entry.get('status')})")
    return violations


def main():
    guard_mode = "--guard" in sys.argv
    verbose = "--verbose" in sys.argv

    if not INDEX_PATH.exists():
        print(f"ERROR: {INDEX_PATH} not found")
        sys.exit(1)

    with open(INDEX_PATH, encoding="utf-8") as f:
        index = json.load(f)

    print(f"Checking {len(index)} entries in eval_index.json...")
    violations = check(index, verbose=verbose)

    total_v = sum(len(v["violations"]) for v in violations)
    print(f"\nResult: {len(violations)} entries with violations, {total_v} total violations")

    if violations and guard_mode:
        print("GUARD FAILED")
        sys.exit(1)
    elif not violations:
        print("All invariants satisfied.")


if __name__ == "__main__":
    main()
