#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_stability_report(paths: list[Path]) -> dict[str, Any]:
    chunks = [_load(path) for path in paths]
    failure_sets = [_failure_percentages(chunk) for chunk in chunks]
    tool_sets = [_tool_list(chunk) for chunk in chunks]
    return {
        "schema_version": "determinex-legacy-taxonomy-stability-v1",
        "chunks": [
            {
                "label": chunk.get("label"),
                "rows_scanned": chunk.get("rows_scanned"),
                "reconstructable_rate": _rate(chunk, "reconstructable_verifier_row"),
                "unrecoverable_rate": _rate(chunk, "unrecoverable"),
                "top_failure_percentages": failure_sets[i],
                "top_replay_tools": tool_sets[i][:25],
            }
            for i, chunk in enumerate(chunks)
        ],
        "class_stability": _class_stability(chunks, failure_sets),
        "tool_stability": _tool_stability(tool_sets),
        "policy": "Use this report to decide whether legacy mining priorities are stable enough for replay promotion attempts.",
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rate(chunk: dict[str, Any], bucket: str) -> float:
    rows = int(chunk.get("rows_scanned") or 0)
    if rows == 0:
        return 0.0
    return round(float((chunk.get("bucket_counts") or {}).get(bucket, 0)) / rows, 6)


def _failure_percentages(chunk: dict[str, Any]) -> dict[str, float]:
    rows = int(chunk.get("rows_scanned") or 0)
    if rows == 0:
        return {}
    out: dict[str, float] = {}
    for row in chunk.get("top_failure_clusters") or []:
        out[str(row.get("failure_class"))] = round(float(row.get("count") or 0) / rows, 6)
    return out


def _tool_list(chunk: dict[str, Any]) -> list[str]:
    return [
        str(row.get("tool")) for row in chunk.get("top_replay_candidates") or [] if row.get("tool")
    ]


def _class_stability(
    chunks: list[dict[str, Any]], percentages: list[dict[str, float]]
) -> dict[str, Any]:
    all_classes = sorted({label for pct in percentages for label in pct})
    rows: list[dict[str, Any]] = []
    for label in all_classes:
        values = [pct.get(label, 0.0) for pct in percentages]
        rows.append(
            {
                "failure_class": label,
                "percentages": values,
                "min": min(values),
                "max": max(values),
                "spread": round(max(values) - min(values), 6),
                "present_in_chunks": sum(1 for value in values if value > 0),
            }
        )
    rows.sort(
        key=lambda row: (row["present_in_chunks"], -row["spread"], row["failure_class"]),
        reverse=True,
    )
    discovered = {
        str(chunks[i].get("label")): sorted(set(percentages[i]) - set().union(*percentages[:i]))
        if i
        else sorted(percentages[i])
        for i in range(len(chunks))
    }
    return {"classes": rows, "new_classes_by_chunk": discovered}


def _tool_stability(tool_sets: list[list[str]]) -> dict[str, Any]:
    if not tool_sets:
        return {"intersection": [], "jaccard_vs_previous": []}
    intersection = set(tool_sets[0])
    for tools in tool_sets[1:]:
        intersection &= set(tools)
    jaccards = []
    for prev, cur in zip(tool_sets, tool_sets[1:]):
        prev_set = set(prev)
        cur_set = set(cur)
        denom = len(prev_set | cur_set) or 1
        jaccards.append(round(len(prev_set & cur_set) / denom, 6))
    return {"intersection": sorted(intersection), "jaccard_vs_previous": jaccards}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare legacy recovery taxonomy stability across scan chunks."
    )
    parser.add_argument("chunks", nargs="+", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assurance/evidence/legacy_taxonomy_stability_report_100k.json"),
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = build_stability_report(args.chunks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.quiet:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
