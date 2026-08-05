#!/usr/bin/env python3
"""
ProgramBench lock audit fix — 2026-06-06.

Applies the structural changes from the audit:
1. Adds official_full_suite_resolved to all board entries
2. Demotes 61 partial-eval "locks" (scored against subset, not full suite)
3. Adds override_type classification (eval_override vs build_only)
4. Keeps 16 genuine full-suite locks intact

Usage: python scripts/pb_lock_audit_fix.py [--dry-run]
"""

import json
import re
import sys
import tarfile
from pathlib import Path

BOARD_PATH = Path("logs/programbench_lock_board.json")
LOCKED_DIR = Path("corpus/programbench/locked")
OVERRIDES_DIR = Path("corpus/programbench/per_tool_overrides")
AUDIT_DATA_PATH = Path("C:/tmp/true_lock_data_v2.json")

DRY_RUN = "--dry-run" in sys.argv


def get_tarball_compile_sh(short_name: str) -> str | None:
    tf_path = LOCKED_DIR / short_name / "submission.tar.gz"
    if not tf_path.exists():
        return None
    try:
        with tarfile.open(tf_path, "r:gz") as tf:
            names = tf.getnames()
            compile_sh = next((n for n in names if n.endswith("compile.sh")), None)
            if compile_sh:
                return tf.extractfile(compile_sh).read().decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def classify_override(content: str) -> tuple[str, str]:
    """Classify compile.sh content as eval_override or build_only."""
    cap_match = re.search(r"del items\[(\d+):\]", content)
    if cap_match:
        return "eval_override", f"del items[{cap_match.group(1)}:] — collection capped"
    if "collect_ignore_glob" in content:
        return "eval_override", "collect_ignore_glob — test collection filter"
    if "pytest_collection_modifyitems" in content and any(
        kw in content for kw in ("tmux", "tui", "interactive", "pexpect", "libtmux")
    ):
        return "eval_override", "pytest_collection_modifyitems — TUI test filter"
    if "conftest.py" in content and "cat >" in content:
        return "build_only", "conftest writes timeout/ini only"
    return "build_only", ""


def slug_to_short(slug: str, audit_data: dict) -> str | None:
    """Extract short tool name that matches audit_data keys."""
    suffix = slug.split("__")[-1] if "__" in slug else slug
    if suffix in audit_data:
        return suffix
    return None


def main() -> None:
    board = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
    audit_data = json.loads(AUDIT_DATA_PATH.read_text(encoding="utf-8"))

    n_demoted = 0
    n_confirmed = 0
    n_override_classified = 0

    for entry in board:
        slug = entry["base_slug"]
        short = slug_to_short(slug, audit_data)

        # --- 1. Set official_full_suite_resolved ---
        if short and short in audit_data:
            ad = audit_data[short]
            resolved = ad["official_full_suite_resolved"]
            entry["official_full_suite_resolved"] = resolved
            entry["official_score_pct"] = round(ad["official_score"] * 100, 1)
            entry["official_passed"] = ad["passed"]
            entry["official_total"] = ad["total"]
            entry["official_not_run"] = ad["not_run"]

            # --- 2. Demote false locks ---
            if not resolved and entry.get("locked_archive"):
                entry["locked_archive"] = False
                entry["partial_eval_100"] = True
                entry["partial_eval_100_note"] = (
                    "Scored 100% against collected subset (not_run excluded from old metric). "
                    "Full official suite not yet validated. Cap/filter must be removed and "
                    "re-evaluated before this can be claimed as a genuine lock."
                )
                n_demoted += 1
                print(
                    f"  DEMOTED: {slug} ({ad['official_score'] * 100:.1f}% official, "
                    f"{ad['not_run']} not_run)"
                )
            elif resolved and entry.get("locked_archive"):
                n_confirmed += 1
        else:
            entry.setdefault("official_full_suite_resolved", False)

        # --- 3. Classify override type ---
        override_type, override_detail = "none", ""
        tarball_content = get_tarball_compile_sh(short) if short else None
        if tarball_content:
            override_type, override_detail = classify_override(tarball_content)
        elif short:
            candidates = list(OVERRIDES_DIR.glob(f"{slug}*")) + list(
                OVERRIDES_DIR.glob(f"*__{short}.*")
            )
            if candidates:
                compile_sh = candidates[0] / "compile.sh"
                if compile_sh.exists():
                    content = compile_sh.read_text(encoding="utf-8", errors="replace")
                    override_type, override_detail = classify_override(content)

        entry["override_type"] = override_type
        if override_detail:
            entry["override_detail"] = override_detail
            n_override_classified += 1

    true_locks = sum(1 for e in board if e.get("locked_archive"))
    print("\nSummary:")
    print(f"  Genuine full-suite locks (locked_archive=True): {true_locks}")
    print(f"  Confirmed: {n_confirmed}, Demoted: {n_demoted}")
    print(f"  Override type classified: {n_override_classified}")
    print(
        f"  Eval overrides on locked tools: "
        f"{sum(1 for e in board if e.get('locked_archive') and e.get('override_type') == 'eval_override')}"
    )

    if DRY_RUN:
        print("\nDRY RUN — board not written.")
    else:
        BOARD_PATH.write_text(json.dumps(board, indent=2), encoding="utf-8")
        print("Board written.")


if __name__ == "__main__":
    main()
