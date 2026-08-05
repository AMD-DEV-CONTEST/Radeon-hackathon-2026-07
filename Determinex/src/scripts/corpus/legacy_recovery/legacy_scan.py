#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.legacy_bucket_classifier import classify_raw_line
from corpus.legacy_recovery.models import LegacyScanItem, iter_jsonl_paths


def scan_legacy_roots(roots: list[Path], *, max_rows: int | None = None) -> dict[str, Any]:
    items: list[LegacyScanItem] = []
    files = iter_jsonl_paths(roots)
    total = 0
    for path in files:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line_number, raw in enumerate(fh, 1):
                if max_rows is not None and total >= max_rows:
                    return _summarize(items, files, truncated=True, max_rows=max_rows)
                total += 1
                items.append(classify_raw_line(raw, path=path, line_number=line_number))
    return _summarize(items, files, truncated=False, max_rows=max_rows)


def _summarize(
    items: list[LegacyScanItem], files: list[Path], *, truncated: bool, max_rows: int | None
) -> dict[str, Any]:
    by_bucket = Counter(item.bucket for item in items)
    by_failure = Counter(label for item in items for label in item.failure_classes)
    by_tool = Counter(item.tool or "unknown" for item in items)
    replay_by_tool = Counter(item.tool or "unknown" for item in items if item.replayable)
    replay_by_failure = Counter(
        label for item in items if item.replayable for label in item.failure_classes
    )
    replay_candidates = _diverse_replay_sample(items, max_total=500, max_per_tool=10)
    return {
        "schema_version": "determinex-legacy-recovery-report-v1",
        "files_scanned": [str(p) for p in files],
        "rows_scanned": len(items),
        "truncated": truncated,
        "max_rows": max_rows,
        "by_bucket": dict(by_bucket),
        "by_failure_class": dict(by_failure),
        "by_tool_top": dict(by_tool.most_common(50)),
        "replay_by_tool_top": dict(replay_by_tool.most_common(100)),
        "replay_by_failure_class": dict(replay_by_failure),
        "replay_candidate_count": sum(1 for item in items if item.replayable),
        "replay_candidates_sample": replay_candidates,
        "training_eligible_rows": 0,
        "policy": "Legacy rows are mined as evidence only; promotion requires fresh verifier replay into a new signed row.",
    }


def _diverse_replay_sample(
    items: list[LegacyScanItem], *, max_total: int, max_per_tool: int
) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    by_tool: Counter[str] = Counter()
    for item in items:
        if not item.replayable:
            continue
        tool = item.tool or "unknown"
        if by_tool[tool] >= max_per_tool:
            continue
        sample.append(item.to_dict())
        by_tool[tool] += 1
        if len(sample) >= max_total:
            break
    return sample


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan quarantined legacy corpus rows and bucket recovery value."
    )
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = scan_legacy_roots(args.roots, max_rows=args.max_rows)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    if not args.quiet:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
