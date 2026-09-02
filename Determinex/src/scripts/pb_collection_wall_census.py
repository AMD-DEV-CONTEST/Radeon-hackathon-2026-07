#!/usr/bin/env python3
"""Classify ProgramBench collection-wall tools from existing reports only."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pb_collection_probe as probe

ROOT = Path(__file__).resolve().parents[1]
LANDSCAPE = ROOT / "corpus" / "programbench" / "campaign_landscape.json"
OUT = ROOT / "corpus" / "programbench" / "pattern_evidence" / "collection_wall_census.md"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def collection_wall_roster() -> list[str]:
    data = load_json(LANDSCAPE)
    rows = data.get("ranked_by_delta") or []
    keep = []
    for row in rows:
        if row.get("failure_class") in {"collection-wall", "partial-collection"}:
            keep.append(str(row["slug"]))
    return keep


def cap_branches(result: dict[str, Any]) -> list[dict[str, Any]]:
    caps = []
    for branch in result["branch_results"]:
        collected = branch.get("collected_count")
        expected = branch.get("expected_count") or 0
        if collected == 400 and expected > 400:
            caps.append(
                {
                    "branch": branch["branch"],
                    "expected": expected,
                    "collected": collected,
                    "emitted": branch.get("emitted_count"),
                }
            )
    return caps


def pile_for(result: dict[str, Any]) -> str:
    if cap_branches(result):
        return "CAP_TRUNCATED"
    totals = result.get("totals") or {}
    true_wall = totals.get("expected_not_collected", 0) + result.get(
        "unmapped_collection_wall_gap", 0
    )
    emission = totals.get("collected_not_emitted", 0)
    behavioral = totals.get("collected_failed", 0)
    if not any((true_wall, emission, behavioral)):
        note_counts = Counter(row.get("branch_class") for row in result.get("branch_results") or [])
        if note_counts.get("UNKNOWN_COLLECTED_SET"):
            return "UNKNOWN"
        return "OK_OR_NO_GAP"
    if emission >= true_wall and emission >= behavioral:
        return "EMISSION_LOSS"
    return "TRUE_WALL_BEHAVIORAL"


def render(
    results: list[dict[str, Any]], failures: list[dict[str, str]], requested_count: int
) -> str:
    pile_counts = Counter(row["pile"] for row in results)
    lines = [
        "# Pattern 002 Collection-Wall Census",
        "",
        "Source: current `corpus/programbench/campaign_landscape.json` rows with `failure_class` in `collection-wall` or `partial-collection`.",
        "Method: `scripts/pb_collection_probe.py` over existing best-known reports only; no evals launched.",
        "",
        "- requested/pasted target: `97` collection-wall tools",
        f"- current machine roster probed: `{requested_count}` tools",
        f"- successful probes: `{len(results)}`",
        f"- unresolved probes: `{len(failures)}`",
        "",
        "## Pile Counts",
        "",
        "| pile | tools |",
        "|---|---:|",
    ]
    for pile, count in sorted(pile_counts.items()):
        lines.append(f"| `{pile}` | {count} |")
    lines.extend(
        ["", "## CAP_TRUNCATED Roster", "", "| tool | cap branches | report |", "|---|---|---|"]
    )
    for row in sorted(
        (r for r in results if r["pile"] == "CAP_TRUNCATED"), key=lambda r: r["task_id"]
    ):
        branch_text = ", ".join(
            f"{b['branch']} {b['collected']}/{b['expected']}" for b in row["cap_branches"]
        )
        lines.append(f"| `{row['task_id']}` | {branch_text} | `{row['report_path']}` |")
    lines.extend(
        [
            "",
            "## EMISSION_LOSS Roster",
            "",
            "| tool | B-C | true wall | behavioral | report |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in sorted(
        (r for r in results if r["pile"] == "EMISSION_LOSS"), key=lambda r: r["task_id"]
    ):
        totals = row["totals"]
        true_wall = totals.get("expected_not_collected", 0) + row.get(
            "unmapped_collection_wall_gap", 0
        )
        lines.append(
            f"| `{row['task_id']}` | {totals.get('collected_not_emitted', 0)} | {true_wall} | "
            f"{totals.get('collected_failed', 0)} | `{row['report_path']}` |"
        )
    lines.extend(
        [
            "",
            "## TRUE_WALL_BEHAVIORAL Roster",
            "",
            "| tool | true wall | behavioral | emission | report |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in sorted(
        (r for r in results if r["pile"] == "TRUE_WALL_BEHAVIORAL"), key=lambda r: r["task_id"]
    ):
        totals = row["totals"]
        true_wall = totals.get("expected_not_collected", 0) + row.get(
            "unmapped_collection_wall_gap", 0
        )
        lines.append(
            f"| `{row['task_id']}` | {true_wall} | {totals.get('collected_failed', 0)} | "
            f"{totals.get('collected_not_emitted', 0)} | `{row['report_path']}` |"
        )
    lines.extend(
        ["", "## Other / Unresolved", "", "| tool | pile or error | report |", "|---|---|---|"]
    )
    for row in sorted(
        (r for r in results if r["pile"] in {"UNKNOWN", "OK_OR_NO_GAP"}), key=lambda r: r["task_id"]
    ):
        lines.append(f"| `{row['task_id']}` | `{row['pile']}` | `{row['report_path']}` |")
    for failure in sorted(failures, key=lambda r: r["tool"]):
        lines.append(f"| `{failure['tool']}` | `{failure['error']}` |  |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    roster = collection_wall_roster()
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for tool in roster:
        try:
            task_id, report_path = probe.load_best_report(tool)
            if task_id.lower() not in str(report_path).lower():
                raise ValueError(
                    f"best_report path does not contain task id {task_id}: {report_path}"
                )
            result = probe.probe_tool(task_id, report_path)
            result["pile"] = pile_for(result)
            result["cap_branches"] = cap_branches(result)
            results.append(result)
        except Exception as exc:  # noqa: BLE001 - census records failures as evidence.
            failures.append({"tool": tool, "error": str(exc)})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(results, failures, len(roster)), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
