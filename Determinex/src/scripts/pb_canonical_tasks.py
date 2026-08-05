#!/usr/bin/env python3
"""Emit ProgramBench canonical task and campaign landscape artifacts.

This is executor-safe: it reads ProgramBench's local task definitions plus
campaign artifacts and writes derived JSON only. It never edits eval_index.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PB_TASKS = Path("T:/Dev/ProgramBench/src/programbench/data/tasks")
EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"
BEST_INDEX = ROOT / "corpus" / "programbench" / "best_known_state.json"
CANONICAL_OUT = ROOT / "corpus" / "programbench" / "canonical_tasks.json"
LANDSCAPE_OUT = ROOT / "corpus" / "programbench" / "campaign_landscape.json"

PUBLIC_TASKS_URL = "https://programbench.com/tasks/"
PUBLIC_TASKS_CITATION = "https://programbench.com/tasks/ lines 8-10, 23-223"
EXCLUDED_LOCAL_TASKS = {
    "testorg__calculator.abc1234": "local fixture/dev task; absent from public 200-instance ProgramBench task page",
}


def parse_task_yaml(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key in {"repository", "commit", "language", "difficulty"}:
            values[key] = value.strip()
    return values


def load_tests(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    branches = data.get("branches") or {}
    branch_rows: list[dict[str, Any]] = []
    total = ignored = active = 0
    for branch, info in branches.items():
        tests = info.get("tests") or []
        ignored_tests = info.get("ignored_tests") or []
        total += len(tests)
        ignored += len(ignored_tests)
        active += max(0, len(tests) - len(ignored_tests))
        branch_rows.append(
            {
                "branch": branch,
                "tests": len(tests),
                "ignored_tests": len(ignored_tests),
                "expected_active": max(0, len(tests) - len(ignored_tests)),
                "ignored_branch": bool(info.get("ignored")),
            }
        )
    return {
        "branches": branch_rows,
        "total_tests": total,
        "ignored_tests": ignored,
        "expected_active_tests": active,
    }


def canonical_tasks() -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for task_dir in sorted(PB_TASKS.iterdir(), key=lambda p: p.name):
        if not task_dir.is_dir() or not (task_dir / "task.yaml").exists():
            continue
        if task_dir.name in EXCLUDED_LOCAL_TASKS:
            excluded.append(
                {
                    "id": task_dir.name,
                    "reason": EXCLUDED_LOCAL_TASKS[task_dir.name],
                    "source_citation": str(task_dir / "task.yaml"),
                }
            )
            continue
        meta = parse_task_yaml(task_dir / "task.yaml")
        tests = load_tests(task_dir / "tests.json")
        tasks.append(
            {
                "id": task_dir.name,
                "repository": meta.get("repository"),
                "commit": meta.get("commit"),
                "language": meta.get("language"),
                "difficulty": meta.get("difficulty"),
                "total_tests": tests["total_tests"],
                "ignored_tests": tests["ignored_tests"],
                "expected_active_tests": tests["expected_active_tests"],
                "branch_count": len(tests["branches"]),
                "branches": tests["branches"],
                "source_citation": {
                    "task_yaml": f"{task_dir / 'task.yaml'}:1",
                    "tests_json": f"{task_dir / 'tests.json'}:1",
                    "public_tasks": PUBLIC_TASKS_CITATION,
                },
            }
        )
    return {
        "schema_version": "determinex-programbench-canonical-tasks-v1",
        "official_task_count": len(tasks),
        "public_task_count": 200,
        "public_tasks_url": PUBLIC_TASKS_URL,
        "public_tasks_citation": PUBLIC_TASKS_CITATION,
        "local_task_dir_count": len(tasks) + len(excluded),
        "excluded_local_tasks": excluded,
        "tasks": tasks,
    }


def slug_candidates(task: dict[str, Any]) -> list[str]:
    task_id = task["id"]
    repo = str(task.get("repository") or "")
    repo_name = repo.split("/")[-1]
    base = task_id.rsplit(".", 1)[0]
    candidates = [task_id, base, repo_name]
    if "__" in base:
        candidates.append(base.split("__", 1)[1])
    commit = str(task.get("commit") or "")
    if repo_name and commit:
        candidates.append(f"{repo_name}-{commit[:7]}")
    return list(dict.fromkeys(c for c in candidates if c))


def load_eval_index() -> list[dict[str, Any]]:
    return json.loads(EVAL_INDEX.read_text(encoding="utf-8"))


def load_best_index() -> dict[str, Any]:
    if not BEST_INDEX.exists():
        return {"tools": {}}
    return json.loads(BEST_INDEX.read_text(encoding="utf-8"))


def normalize_status(status: str | None) -> str:
    return str(status or "unverdicted")


def classify_failure(row: dict[str, Any], status: str) -> str:
    if status in {
        "strict_lock",
        "reference_parity",
        "upstream_skips",
        "ceiling_confirmed",
        "parked",
    }:
        return status
    failed = int(row.get("failed") or row.get("errors") or 0)
    not_run = int(row.get("not_run") or 0)
    skipped = int(row.get("skipped") or 0)
    total = row.get("total")
    if row.get("best_report") is None and total is None:
        return "no-data"
    if not_run:
        return "collection-wall"
    if failed:
        return "behavioral"
    if skipped:
        return "skip-census"
    return "unclassified"


def campaign_landscape(canonical: dict[str, Any]) -> dict[str, Any]:
    eval_rows = load_eval_index()
    best = load_best_index().get("tools", {})
    by_slug = {str(row.get("slug")): row for row in eval_rows if row.get("slug")}
    canonical_ids = {task["id"] for task in canonical["tasks"]}
    candidates_to_task: dict[str, str] = {}
    for task in canonical["tasks"]:
        for candidate in slug_candidates(task):
            candidates_to_task[candidate] = task["id"]

    extras: list[dict[str, Any]] = []
    rows_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eval_rows:
        slug = str(row.get("slug") or "")
        if row.get("canonical_slug"):
            mapped = candidates_to_task.get(str(row.get("canonical_slug")))
        else:
            mapped = candidates_to_task.get(slug)
        if mapped:
            rows_by_task[mapped].append(row)
        elif not row.get("alias_of"):
            extras.append(
                {
                    "slug": slug,
                    "status": row.get("status"),
                    "reason": "not in canonical task candidates",
                }
            )

    tools: list[dict[str, Any]] = []
    buckets: Counter[str] = Counter()
    lanes: dict[str, list[dict[str, Any]]] = {
        "LANE_P": [],
        "LANE_B": [],
        "LANE_M": [],
        "LANE_0": [],
    }
    for task in canonical["tasks"]:
        task_id = task["id"]
        eval_candidates = rows_by_task.get(task_id, [])
        primary = eval_candidates[0] if eval_candidates else {}
        status_rank = {
            "strict_lock": 0,
            "reference_parity": 1,
            "upstream_skips": 2,
            "ceiling_confirmed": 3,
        }
        if eval_candidates:
            primary = sorted(
                eval_candidates,
                key=lambda row: (
                    status_rank.get(str(row.get("status")), 50),
                    0 if row.get("slug") == task_id else 1,
                    str(row.get("slug") or ""),
                ),
            )[0]
        best_row = best.get(str(primary.get("slug") or task_id)) or best.get(task_id) or {}
        status = normalize_status(primary.get("status") or best_row.get("eval_index_status"))
        failure_class = classify_failure(best_row, status)
        passed = best_row.get("passed")
        total = best_row.get("total") or task.get("expected_active_tests")
        delta = best_row.get("delta_to_lock")
        if delta is None and passed is not None and total is not None:
            delta = int(total) - int(passed)
        row = {
            "id": task_id,
            "repository": task.get("repository"),
            "language": task.get("language"),
            "canonical_total_tests": task.get("total_tests"),
            "canonical_expected_active_tests": task.get("expected_active_tests"),
            "eval_index_status": status,
            "best_passed": passed,
            "best_total": best_row.get("total"),
            "best_failed": best_row.get("failed"),
            "best_errors": best_row.get("errors"),
            "best_skipped": best_row.get("skipped"),
            "best_not_run": best_row.get("not_run"),
            "delta_to_lock": delta,
            "failure_class": failure_class,
            "best_report": best_row.get("best_report"),
            "best_tarball": best_row.get("best_tarball"),
            "best_overrides": best_row.get("best_overrides"),
            "eval_index_slugs": [r.get("slug") for r in eval_candidates],
        }
        tools.append(row)
        buckets[failure_class] += 1
        if failure_class == "collection-wall":
            lanes["LANE_P"].append(row)
        elif failure_class == "behavioral":
            lanes["LANE_B"].append(row)
        elif (task.get("total_tests") or 0) > 3000:
            lanes["LANE_M"].append(row)
        elif failure_class == "no-data":
            lanes["LANE_0"].append(row)

    lanes["LANE_P"].sort(key=lambda r: (-(r.get("best_not_run") or 0), r["id"]))
    lanes["LANE_B"].sort(
        key=lambda r: (
            r.get("delta_to_lock") if r.get("delta_to_lock") is not None else 10**9,
            r["id"],
        )
    )
    lanes["LANE_M"].sort(key=lambda r: (-(r.get("canonical_total_tests") or 0), r["id"]))
    lanes["LANE_0"].sort(key=lambda r: r["id"])
    return {
        "schema_version": "determinex-programbench-campaign-landscape-v1",
        "canonical_task_count": canonical["official_task_count"],
        "bucket_counts": dict(sorted(buckets.items())),
        "extra_eval_index_rows": extras,
        "attack_plan": {
            lane: [
                {
                    "id": r["id"],
                    "delta_to_lock": r.get("delta_to_lock"),
                    "best_not_run": r.get("best_not_run"),
                    "best_report": r.get("best_report"),
                }
                for r in rows[:10]
            ]
            for lane, rows in lanes.items()
        },
        "lane_counts": {lane: len(rows) for lane, rows in lanes.items()},
        "tools": tools,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-out", default=str(CANONICAL_OUT))
    parser.add_argument("--landscape-out", default=str(LANDSCAPE_OUT))
    args = parser.parse_args()
    canonical = canonical_tasks()
    canonical_path = Path(args.canonical_out)
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_text(
        json.dumps(canonical, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    landscape = campaign_landscape(canonical)
    landscape_path = Path(args.landscape_out)
    landscape_path.parent.mkdir(parents=True, exist_ok=True)
    landscape_path.write_text(
        json.dumps(landscape, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"canonical_tasks={canonical_path} count={canonical['official_task_count']} local_dirs={canonical['local_task_dir_count']}"
    )
    print(f"campaign_landscape={landscape_path} lanes={landscape['lane_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
