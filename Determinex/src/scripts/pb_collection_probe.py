#!/usr/bin/env python3
"""Diagnose ProgramBench collection-wall gaps.

For a tool eval report, compare per-branch:
A. EXPECTED ids from ProgramBench tests.json
B. COLLECTED pytest nodeids reconstructed from verbose pytest output
C. EMITTED testcase ids reconstructed from final JUnit XML or eval rows

This script measures only. It does not edit eval_index or launch evals.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PB_TASKS = Path("T:/Dev/ProgramBench/src/programbench/data/tasks")
BEST_INDEX = ROOT / "corpus" / "programbench" / "best_known_state.json"
DEFAULT_OUT = ROOT / "assurance" / "evidence" / "programbench_collection_probe"

STATUS_WORDS = {"PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS", "RERUN"}


@dataclass(frozen=True)
class BranchProbe:
    branch: str
    expected_count: int
    collected_count: int | None
    emitted_count: int
    expected_not_collected: list[str]
    collected_not_emitted: list[str]
    collected_failed: list[str]
    branch_class: str
    controlling_number: int
    collected_reconstructable: bool
    collection_summary_count: int | None
    collection_error_count: int


def normalize_nodeid(nodeid: str) -> str:
    nodeid = nodeid.strip()
    nodeid = nodeid.split(" ", 1)[0]
    nodeid = nodeid.replace("\\", "/")
    parts = nodeid.split("::")
    path = parts[0]
    stem = path[:-3] if path.endswith(".py") else path
    module = stem.replace("/", ".")
    return ".".join([module, *parts[1:]])


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def report_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    data = report
    rows = data.get("test_results") or data.get("results") or []
    return [row for row in rows if isinstance(row, dict)]


def report_logs(report: dict[str, Any]) -> list[dict[str, Any]]:
    logs = report.get("log") or []
    return [row for row in logs if isinstance(row, dict)]


def load_expected(task_id: str) -> dict[str, set[str]]:
    task_dir = resolve_task_dir(task_id)
    data = load_json(task_dir / "tests.json")
    expected: dict[str, set[str]] = {}
    for branch, info in (data.get("branches") or {}).items():
        expected[branch] = set(str(name) for name in (info.get("tests") or []))
    return expected


def resolve_task_dir(task_id: str) -> Path:
    direct = PB_TASKS / task_id
    if direct.exists():
        return direct
    matches = sorted(PB_TASKS.glob(f"*__{task_id}.*"))
    if len(matches) == 1:
        return matches[0]
    matches = sorted(PB_TASKS.glob(f"{task_id}.*"))
    if len(matches) == 1:
        return matches[0]
    raise SystemExit(f"cannot resolve PB task dir for {task_id}")


def row_status(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").lower()
    return "failure" if status == "failed" else status


def row_text(row: dict[str, Any]) -> str:
    extra = row.get("extra") or {}
    values = [row.get("output"), row.get("message"), row.get("text")]
    values.extend(extra.get(key) for key in ("output", "message", "text"))
    return "\n".join(str(value or "") for value in values)


def parse_collected_ids(rows: Iterable[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    line_pat = re.compile(
        r"^([A-Za-z0-9_./\\-]+\.py(?:::[^\s]+)+)\s+(" + "|".join(STATUS_WORDS) + r")\b"
    )
    for row in rows:
        for line in row_text(row).splitlines():
            match = line_pat.match(line.strip())
            if match:
                found.add(normalize_nodeid(match.group(1)))
    return found


def parse_collection_summary(row: dict[str, Any]) -> tuple[int, int] | None:
    match = re.search(r"collected\s+(\d+)\s+items(?:\s*/\s*(\d+)\s+errors?)?", row_text(row))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def parse_xml_testcases(rows: Iterable[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    case_pat = re.compile(
        r"<testcase\b[^>]*\bclassname=\"([^\"]+)\"[^>]*\bname=\"([^\"]+)\"", re.IGNORECASE
    )
    for row in rows:
        text = row_text(row)
        if "<testcase" not in text:
            continue
        for cls, name in case_pat.findall(text):
            found.add(f"{html.unescape(cls)}.{html.unescape(name)}")
    return found


def emitted_ids(rows: Iterable[dict[str, Any]]) -> set[str]:
    row_list = list(rows)
    xml_ids = parse_xml_testcases(row_list)
    if xml_ids:
        return xml_ids
    return {
        str(row.get("name")) for row in row_list if row_status(row) != "not_run" and row.get("name")
    }


def failed_ids(rows: Iterable[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("name"))
        for row in rows
        if row.get("name") and row_status(row) in {"failure", "error"}
    }


def classify_branch(
    expected_not_collected: set[str],
    collected_not_emitted: set[str],
    collected_failed: set[str],
    collected_reconstructable: bool,
) -> tuple[str, int]:
    if not collected_reconstructable:
        return "UNKNOWN_COLLECTED_SET", 0
    counts = {
        "COLLECTION_WALL": len(expected_not_collected),
        "EMISSION_LOSS": len(collected_not_emitted),
        "BEHAVIORAL": len(collected_failed),
    }
    nonzero = {k: v for k, v in counts.items() if v}
    if not nonzero:
        return "OK", 0
    max_count = max(nonzero.values())
    winners = [k for k, v in nonzero.items() if v == max_count]
    if len(nonzero) > 1:
        return "MIXED", max_count
    return winners[0], max_count


def probe_branch(
    branch: str,
    expected: set[str],
    rows: list[dict[str, Any]],
    collected_by_branch: dict[str, set[str]],
    collection_summary_by_branch: dict[str, tuple[int, int]],
    emitted_by_branch: dict[str, set[str]],
) -> BranchProbe:
    branch_rows = [row for row in rows if str(row.get("branch") or "") == branch]
    collected = collected_by_branch.get(branch, set())
    collection_summary = collection_summary_by_branch.get(branch)
    emitted = emitted_by_branch.get(branch, set())
    failed = failed_ids(branch_rows)
    reconstructable = bool(collected)
    if reconstructable:
        expected_not_collected = expected - collected
        collected_not_emitted = collected - emitted
        collected_failed = expected & collected & failed
    else:
        expected_not_collected = set()
        collected_not_emitted = set()
        collected_failed = set()
    branch_class, controlling = classify_branch(
        expected_not_collected,
        collected_not_emitted,
        collected_failed,
        reconstructable,
    )
    collection_summary_count = collection_summary[0] if collection_summary else None
    collection_error_count = collection_summary[1] if collection_summary else 0
    if not reconstructable and collection_error_count:
        branch_class = "COLLECTION_WALL_UNMAPPED"
        controlling = max(0, len(expected) - len(emitted))
    return BranchProbe(
        branch=branch,
        expected_count=len(expected),
        collected_count=len(collected) if reconstructable else collection_summary_count,
        emitted_count=len(emitted),
        expected_not_collected=sorted(expected_not_collected),
        collected_not_emitted=sorted(collected_not_emitted),
        collected_failed=sorted(collected_failed),
        branch_class=branch_class,
        controlling_number=controlling,
        collected_reconstructable=reconstructable,
        collection_summary_count=collection_summary_count,
        collection_error_count=collection_error_count,
    )


def emitted_by_branch(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("branch") or "unknown")].append(row)
    return {branch: emitted_ids(branch_rows) for branch, branch_rows in grouped.items()}


def collected_by_branch(
    logs: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, set[str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(logs):
        branch = str(row.get("branch") or "")
        if not branch and parse_collected_ids([row]):
            for next_row in logs[index + 1 :]:
                branch = str(next_row.get("branch") or "")
                if branch:
                    break
        if branch:
            grouped[branch].append(row)
    for row in rows:
        branch = str(row.get("branch") or "")
        if branch:
            grouped[branch].append(row)
    return {branch: parse_collected_ids(branch_rows) for branch, branch_rows in grouped.items()}


def collection_summary_by_branch(logs: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    found: dict[str, tuple[int, int]] = {}
    for index, row in enumerate(logs):
        summary = parse_collection_summary(row)
        if not summary:
            continue
        branch = str(row.get("branch") or "")
        if not branch:
            for next_row in logs[index + 1 :]:
                branch = str(next_row.get("branch") or "")
                if branch:
                    break
        if branch:
            found[branch] = summary
    return found


def probe_tool(task_id: str, report_path: Path) -> dict[str, Any]:
    expected = load_expected(task_id)
    report = load_json(report_path)
    rows = report_rows(report)
    logs = report_logs(report)
    emitted = emitted_by_branch(rows)
    collected = collected_by_branch(logs, rows)
    summaries = collection_summary_by_branch(logs)
    branches = sorted(set(expected) | set(emitted) | {str(row.get("branch") or "") for row in rows})
    branch_results = [
        probe_branch(branch, expected.get(branch, set()), rows, collected, summaries, emitted)
        for branch in branches
        if branch
    ]
    totals = Counter()
    reconstructable_not_run = 0
    rows_by_branch = defaultdict(list)
    for row in rows:
        rows_by_branch[str(row.get("branch") or "unknown")].append(row)
    for result in branch_results:
        totals["expected_not_collected"] += len(result.expected_not_collected)
        totals["collected_not_emitted"] += len(result.collected_not_emitted)
        totals["collected_failed"] += len(result.collected_failed)
        if result.collected_reconstructable:
            reconstructable_not_run += sum(
                1 for row in rows_by_branch.get(result.branch, []) if row_status(row) == "not_run"
            )
    denominator = (
        totals["expected_not_collected"]
        + totals["collected_not_emitted"]
        + totals["collected_failed"]
    )
    pct = {
        "true_collection_wall_pct": round(totals["expected_not_collected"] / denominator * 100, 1)
        if denominator
        else None,
        "emission_loss_pct": round(totals["collected_not_emitted"] / denominator * 100, 1)
        if denominator
        else None,
        "behavioral_pct": round(totals["collected_failed"] / denominator * 100, 1)
        if denominator
        else None,
    }
    report_counts = Counter(row_status(row) for row in rows)
    return {
        "task_id": task_id,
        "report_path": str(report_path),
        "report_counts": dict(report_counts),
        "reconstructable_not_run": reconstructable_not_run,
        "totals": dict(totals),
        "unmapped_collection_wall_gap": sum(
            result.controlling_number
            for result in branch_results
            if result.branch_class == "COLLECTION_WALL_UNMAPPED"
        ),
        "percentages_over_classified_gap": pct,
        "branch_results": [asdict(result) for result in branch_results],
    }


def load_best_report(tool: str) -> tuple[str, Path]:
    best = load_json(BEST_INDEX).get("tools", {})
    if tool in best and best[tool].get("best_report"):
        task_id = tool
        path = best[tool]["best_report"]
    else:
        matches = [k for k in best if tool.lower() in k.lower() and best[k].get("best_report")]
        if not matches:
            raise SystemExit(f"no best report found for {tool}")
        matches.sort(key=lambda k: (len(k), k))
        task_id = matches[0]
        path = best[task_id]["best_report"]
    report_path = Path(path)
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    if not report_path.exists():
        raise SystemExit(f"report does not exist: {report_path}")
    return task_id, report_path


def render_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# ProgramBench Collection Probe",
        "",
        "| tool | not_run in report | reconstructable not_run | true collection | emission loss | behavioral | classification note |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    total_collection = total_emission = total_behavioral = 0
    for result in results:
        counts = result["report_counts"]
        totals = result["totals"]
        total_collection += totals.get("expected_not_collected", 0)
        total_emission += totals.get("collected_not_emitted", 0)
        total_behavioral += totals.get("collected_failed", 0)
        note_counts = Counter(row["branch_class"] for row in result["branch_results"])
        lines.append(
            f"| `{result['task_id']}` | {counts.get('not_run', 0)} | {result['reconstructable_not_run']} | "
            f"{totals.get('expected_not_collected', 0)} | {totals.get('collected_not_emitted', 0)} | "
            f"{totals.get('collected_failed', 0)} | {dict(note_counts)}; unmapped={result.get('unmapped_collection_wall_gap', 0)} |"
        )
    denom = total_collection + total_emission + total_behavioral
    if denom:
        lines.extend(
            [
                "",
                "## Aggregate Classified Gap",
                "",
                f"- TRUE collection wall: `{total_collection}/{denom}` = `{round(total_collection / denom * 100, 1)}%`",
                f"- Emission loss: `{total_emission}/{denom}` = `{round(total_emission / denom * 100, 1)}%`",
                f"- Behavioral: `{total_behavioral}/{denom}` = `{round(total_behavioral / denom * 100, 1)}%`",
            ]
        )
    lines.extend(["", "## Branch Detail", ""])
    for result in results:
        lines.append(f"### {result['task_id']}")
        lines.append("")
        lines.append(
            "| branch | A expected | B collected | C emitted | A-B | B-C | failed collected | class |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
        for branch in result["branch_results"]:
            b_count = (
                "unknown" if branch["collected_count"] is None else str(branch["collected_count"])
            )
            lines.append(
                f"| `{branch['branch']}` | {branch['expected_count']} | {b_count} | {branch['emitted_count']} | "
                f"{len(branch['expected_not_collected'])} | {len(branch['collected_not_emitted'])} | "
                f"{len(branch['collected_failed'])} | `{branch['branch_class']}` |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tools", nargs="+")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_results = []
    for tool in args.tools:
        task_id, report = load_best_report(tool)
        result = probe_tool(task_id, report)
        all_results.append(result)
        (out_dir / f"{tool}_collection_probe.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    (out_dir / "collection_probe_summary.md").write_text(
        render_markdown(all_results), encoding="utf-8"
    )
    print(out_dir / "collection_probe_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
