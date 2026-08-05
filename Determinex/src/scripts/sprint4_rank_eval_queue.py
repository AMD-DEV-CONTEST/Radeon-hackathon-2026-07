#!/usr/bin/env python3
"""Rank Sprint 4 factory scaffolds for scarce serial Docker eval.

Generation/smoke can be broad. Eval must be narrow. This ranker separates
"generated successfully" from "semantically worth evaluating" so weak family
coincidences do not burn Docker time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HIGH_CONFIDENCE_FAMILIES = {
    "search_grep",
    "file_renamers",
    "shell_coreutils",
    "text_diff",
    "formatters",
    "git_wrappers",
    "rust_cli",
}

MEDIUM_CONFIDENCE_FAMILIES = {
    "json_yaml_toml",
    "csv_table",
    "regex_tools",
    "archive_compression",
    "network_http",
    "tui_terminal",
    "config_env",
    "database",
}

# Sprint-4 audit fleshed out the deferred families. Remaining defers are
# only those families that genuinely cannot be auto-generated meaningfully
# (e.g. real image rendering needs PIL, real game simulators need engine state).
# Most former entries here now route through proper families/subtypes via
# INSTANCE_SUBTYPE_OVERRIDES in generator_lib.py.
DOMAIN_DEFER_SUBSTRINGS: dict[str, str] = {
    # Empty — all formerly-deferred tools now have family + subtype routing.
    # Re-add an entry here ONLY if a tool genuinely has no eval-worthy v1.
}

STRONG_NAME_HINTS = {
    "the_silver_searcher": "search_grep",
    "amber": "search_grep",
    "srgn": "search_grep",
    "pls": "shell_coreutils",
    "parallel-disk-usage": "shell_coreutils",
    "gdu": "shell_coreutils",
    "rhit": "shell_coreutils",
    "clog-cli": "git_wrappers",
    "git-graph": "git_wrappers",
}


def _tool_name(instance: str) -> str:
    if "__" in instance:
        return instance.split("__", 1)[1].split(".", 1)[0]
    return instance.split(".", 1)[0]


def _domain_defer_reason(instance: str) -> str | None:
    tool = _tool_name(instance).lower()
    for needle, reason in DOMAIN_DEFER_SUBSTRINGS.items():
        if needle in tool:
            return reason
    return None


def _family_test_count(rec: dict) -> int:
    family = rec.get("family", "")
    for fam, count in (rec.get("signals") or {}).get("by_test") or []:
        if fam == family:
            return int(count)
    return 0


def _has_name_signal(rec: dict) -> bool:
    family = rec.get("family", "")
    signals = rec.get("signals") or {}
    by_name = signals.get("by_name") or []
    tool = str(signals.get("tool") or _tool_name(rec.get("instance", ""))).lower()
    return family in by_name or STRONG_NAME_HINTS.get(tool) == family


def eval_worthiness(rec: dict) -> tuple[int, str]:
    """Return (tier, reason). Higher tier should eval sooner."""
    family = rec.get("family", "")
    defer = _domain_defer_reason(rec.get("instance", ""))
    if defer:
        return -1, "defer: " + defer
    name_signal = _has_name_signal(rec)
    test_count = _family_test_count(rec)
    if name_signal and family in HIGH_CONFIDENCE_FAMILIES:
        return 3, "strong name/family match"
    if test_count >= 50 and family in HIGH_CONFIDENCE_FAMILIES:
        return 3, f"strong test signal ({test_count})"
    if test_count >= 25 and family in HIGH_CONFIDENCE_FAMILIES:
        return 2, f"moderate test signal ({test_count})"
    if name_signal and family in MEDIUM_CONFIDENCE_FAMILIES:
        return 1, "medium family name match"
    if test_count >= 40 and family in MEDIUM_CONFIDENCE_FAMILIES:
        return 1, f"medium family test signal ({test_count})"
    return 0, f"weak family evidence (name={name_signal}, tests={test_count})"


def _rank_score(rec: dict) -> tuple:
    worth, _reason = eval_worthiness(rec)
    base = rec.get("base_score") or 0.0
    headroom = 100.0 - base
    return (worth, headroom, -base)


def _tier_label(tier: int) -> str:
    return {3: "strong", 2: "moderate", 1: "medium", 0: "weak", -1: "defer"}[tier]


def main() -> int:
    smoke_log = ROOT / "logs" / "mass_run_v2" / "sprint4_smoke_pass.json"
    if not smoke_log.is_file():
        print(f"ERROR: smoke pass log not found at {smoke_log}")
        return 1
    data = json.loads(smoke_log.read_text(encoding="utf-8"))
    ok = [r for r in data["records"] if r.get("status") == "OK"]
    ranked = sorted(ok, key=_rank_score, reverse=True)

    out_md = ROOT / "logs" / "mass_run_v2" / "sprint4_eval_queue.md"
    out_json = ROOT / "logs" / "mass_run_v2" / "sprint4_eval_queue.json"

    lines = [
        "# Sprint 4 Eval Queue (ranked)",
        "",
        f"Total smoke-passing scaffolds: **{len(ranked)}**",
        "",
        "Rank by: (family evidence, headroom, low base score). Run serially under guard.",
        "",
        "Promotion rule:",
        "- delta >= +3pp -> keep v1",
        "- delta >= +10pp -> flag for v2 refinement",
        "- delta < +3pp or regression -> discard, record family lesson",
        "",
        "| Rank | Instance | Family | Base % | Evidence | Notes |",
        "|---:|---|---|---:|:---:|---|",
    ]

    json_rows = []
    for i, r in enumerate(ranked, 1):
        tier, reason = eval_worthiness(r)
        base = r.get("base_score")
        base_str = f"{base:.2f}" if base is not None else "-"
        notes = reason
        if base is not None and base < 5:
            notes += "; lots of headroom"
        elif base is not None and base > 50:
            notes += "; high base; v1 may not move"
        lines.append(
            f"| {i} | `{r['instance']}` | {r.get('family', '?')} | "
            f"{base_str} | {_tier_label(tier)} | {notes} |"
        )
        json_rows.append(
            {
                "rank": i,
                "instance": r["instance"],
                "family": r.get("family"),
                "base_score": r.get("base_score"),
                "confidence": _tier_label(tier),
                "eval_worthiness": tier,
                "evidence_reason": reason,
                "factory_dir": f"T:/determinex-programbench/determinex_pb_factory_{r['instance']}_v1",
            }
        )

    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_json.write_text(
        json.dumps({"ranked": json_rows, "total": len(json_rows)}, indent=2), encoding="utf-8"
    )

    print(f"Sprint 4 eval queue ranked: {len(ranked)} entries")
    print(f"  markdown: {out_md}")
    print(f"  json:     {out_json}")
    print()
    print("Top 15 ranked:")
    short = {3: "S", 2: "M", 1: "m", 0: "W", -1: "D"}
    for i, r in enumerate(ranked[:15], 1):
        tier, _reason = eval_worthiness(r)
        base = r.get("base_score")
        base_str = f"{base:>6.2f}" if base is not None else "     -"
        print(
            f"  {i:>3}. [{short[tier]}] {r['instance']:<55} {r.get('family', '?'):<20} base={base_str}%"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
