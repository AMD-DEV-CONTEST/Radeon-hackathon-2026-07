#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.legacy_failure_clusterer import build_failure_taxonomy
from corpus.legacy_recovery.legacy_replay_planner import build_replay_plan
from corpus.legacy_recovery.legacy_scan import scan_legacy_roots
from corpus.legacy_recovery.programbench_priority_model import build_priority_model


def run_chunk(roots: list[Path], *, rows: int, label: str, output_dir: Path) -> dict[str, Any]:
    scan = scan_legacy_roots(roots, max_rows=rows)
    taxonomy = build_failure_taxonomy(scan)
    replay = build_replay_plan(scan)
    priority = build_priority_model(scan)
    artifact = {
        "schema_version": "determinex-legacy-recovery-chunk-v1",
        "label": label,
        "rows_requested": rows,
        "rows_scanned": scan["rows_scanned"],
        "truncated": scan["truncated"],
        "bucket_counts": scan["by_bucket"],
        "parse_error_count": scan["by_bucket"].get("unrecoverable", 0),
        "top_tools": scan["by_tool_top"],
        "top_languages": _language_counts(scan),
        "top_failure_clusters": taxonomy["clusters"][:25],
        "top_replay_candidates": replay["tools"][:50],
        "top_priority_tools": priority["tools"][:50],
        "replay_candidate_count": scan["replay_candidate_count"],
        "dedupe_rate": 0.0,
        "promotion_attempts": 0,
        "promotion_successes": 0,
        "promotion_rejects": 0,
        "training_eligible_rows_created": 0,
        "policy": "Chunk scans mine legacy evidence only. Promotion requires LEGACY_REPLAY_PROMOTION_LOCK_001 fresh verifier replay.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"legacy_recovery_scan_{label}.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def _language_counts(scan: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in scan.get("replay_candidates_sample") or []:
        lang = str(row.get("language_guess") or "unknown")
        counts[lang] = counts.get(lang, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a named chunked legacy recovery scan.")
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("assurance/evidence"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    artifact = run_chunk(args.roots, rows=args.rows, label=args.label, output_dir=args.output_dir)
    if not args.quiet:
        print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
