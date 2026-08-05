#!/usr/bin/env python3
"""Download public SWE-bench task instances for Track 2 experiments.

The generated JSONL intentionally excludes gold patches and evaluator tests.
Those fields remain available in the original Hugging Face dataset for the
official evaluator, but must not be placed in the agent prompt.
"""

from __future__ import annotations

import argparse
import json
import random
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any


DATASETS = {
    "full": "SWE-bench/SWE-bench",
    "lite": "SWE-bench/SWE-bench_Lite",
    "verified": "SWE-bench/SWE-bench_Verified",
}

PUBLIC_FIELDS = (
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
    "version",
    "issue_url",
    "pr_url",
    "environment_setup_commit",
    "hints_text",
    "image_name",
)


def _load_dataset(dataset_name: str, split: str):
    try:
        from datasets import load_dataset
    except ImportError:
        return _load_dataset_viewer(dataset_name, split)
    try:
        return load_dataset(dataset_name, split=split)
    except Exception:
        # Some minimal workers have ``datasets`` installed but no compatible
        # parquet backend or Hub transport.  The public Viewer remains a
        # dependency-light read-only fallback.
        return _load_dataset_viewer(dataset_name, split)


def _viewer_get(path: str, **params: str) -> dict[str, Any]:
    """Read one Dataset Viewer response without requiring ``datasets``."""
    query = urlencode({key: value for key, value in params.items() if value is not None})
    request = Request(f"https://datasets-server.huggingface.co/{path}?{query}")
    token = os.getenv("HF_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=60) as response:  # noqa: S310 - fixed HTTPS host
        return json.load(response)


def _load_dataset_viewer(dataset_name: str, split: str) -> list[dict[str, Any]]:
    """Paginate public rows from Hugging Face's read-only Dataset Viewer API."""
    config = "default"
    try:
        split_info = _viewer_get("splits", dataset=dataset_name)
        available = split_info.get("splits", [])
        matching = [
            item for item in available
            if item.get("split") == split or item.get("split_name") == split
        ]
        if matching:
            config = matching[0].get("config", config)
    except Exception:
        # The rows endpoint gives a more useful error if a dataset is private
        # or temporarily unavailable, so retain the default-config attempt.
        pass

    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        payload = _viewer_get(
            "rows",
            dataset=dataset_name,
            config=config,
            split=split,
            offset=str(offset),
            length="100",
        )
        page = [item.get("row", {}) for item in payload.get("rows", [])]
        rows.extend(page)
        total = payload.get("num_rows_total")
        if not page or len(page) < 100 or (total is not None and len(rows) >= int(total)):
            break
        offset += len(page)
    if not rows:
        raise RuntimeError(f"Dataset Viewer returned no rows for {dataset_name} split={split}")
    return rows


def _public_task(row: Any) -> dict[str, Any]:
    if hasattr(row, "get"):
        return {field: row.get(field) for field in PUBLIC_FIELDS if row.get(field) is not None}
    return {field: getattr(row, field) for field in PUBLIC_FIELDS if hasattr(row, field)}


def _prompt(task: dict[str, Any]) -> str:
    instance_id = task.get("instance_id", "unknown")
    repo = task.get("repo", "")
    base_commit = task.get("base_commit", "")
    issue = task.get("problem_statement", "")
    return (
        f"Resolve SWE-bench task {instance_id}.\n"
        f"Repository: {repo}\n"
        f"Base commit: {base_commit}\n\n"
        f"Issue:\n{issue}\n\n"
        "Work only in the provided repository checkout. Inspect the code, "
        "implement the fix, run relevant tests, and leave a unified diff."
    )


def build_tasks(dataset_name: str, split: str, limit: int | None, seed: int) -> list[dict[str, Any]]:
    dataset = _load_dataset(dataset_name, split)
    rows = [_public_task(row) for row in dataset]
    random.Random(seed).shuffle(rows)
    if limit is not None:
        rows = rows[:limit]
    # Keep the agent-facing allowlist flat so the runner can validate and
    # checkout a public manifest without carrying evaluator-only fields.  The
    # previous nested ``task`` shape was easy to misread as a ready-to-run
    # SWE-bench record and caused public manifests to fail validation.
    return [
        {
            "instance_id": row.get("instance_id"),
            "repo": row.get("repo"),
            "base_commit": row.get("base_commit"),
            "problem_statement": row.get("problem_statement"),
            "prompt": _prompt(row),
        }
        for row in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="lite")
    parser.add_argument("--dataset_name", default=None, help="Override the official Hugging Face dataset ID")
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset_name = args.dataset_name or DATASETS[args.dataset]
    tasks = build_tasks(dataset_name, args.split, args.limit, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for task in tasks:
            handle.write(json.dumps(task, ensure_ascii=False) + "\n")
    print(f"Wrote {len(tasks)} public tasks from {dataset_name} to {args.output}")


if __name__ == "__main__":
    main()
