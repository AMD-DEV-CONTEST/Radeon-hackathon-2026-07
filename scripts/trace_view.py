#!/usr/bin/env python3
"""Trace run facts viewing script: load and print six views from a saved run directory.

Usage:
    python scripts/trace_view.py --run-dir .agently/runs/insurance/traces/<task_id>

Output views:
    1. task_view       - execution level: trigger flow execution start/completion/failure
    2. stage_view      - stage level: instance count/completion/failure per chunk
    3. operation_view  - operation level: all business-layer facts
    4. attempt_view    - attempt level: model request telemetry facts grouped
    5. retrieval_view  - insurance-specific: RAG retrieval events
    6. citation_view   - insurance-specific: citation/evidence events

Design principles:
    Trace only records facts (no quality judgment; that is Eval's responsibility).
    This script only reads saved facts; it does not recompute or infer anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add the project root to the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.observability.trace_log import (
    attempt_view,
    citation_view,
    operation_view,
    retrieval_view,
    stage_view,
    task_view,
)


# - Output utilities

def _print_section(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def _to_json_str(data: Any, indent: int = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent)


def _load_events(run_dir: Path) -> list[dict[str, Any]]:
    """Load the event list from events.jsonl or run.json."""

    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        events: list[dict[str, Any]] = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events

    run_path = run_dir / "run.json"
    if run_path.exists():
        run_data = json.loads(run_path.read_text(encoding="utf-8"))
        return run_data.get("events", [])

    raise FileNotFoundError(
        f"No event file found: {events_path} or {run_path}"
    )


def _load_summary(run_dir: Path) -> dict[str, Any] | None:
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return None


def _print_run_overview(run_dir: Path, summary: dict[str, Any] | None) -> None:
    _print_section("Run Overview")
    print(f"  Run directory: {run_dir}")
    if summary:
        print(f"  task_id:          {summary.get('task_id')}")
        print(f"  execution_id:     {summary.get('execution_id')}")
        print(f"  status:           {summary.get('status')}")
        print(f"  session_id:       {summary.get('session_id')}")
        print(f"  user_input:       {summary.get('user_input')}")
        print(f"  query_type:       {summary.get('query_type')}")
        print(f"  candidate_count:  {summary.get('candidate_count')}")
        print(f"  context_item_count: {summary.get('context_item_count')}")
        print(f"  citation_count:   {summary.get('citation_count')}")
        print(f"  source_count:     {summary.get('source_count')}")
        print(f"  event_count:      {summary.get('event_count')}")
    else:
        print("  (summary.json not found, skipping overview)")


def _print_task_view(events: list[dict[str, Any]]) -> None:
    _print_section("1. Task View - execution-level facts")
    rows = task_view(events)
    if not rows:
        print("  (no execution-level events)")
        return
    print(_to_json_str(rows))


def _print_stage_view(events: list[dict[str, Any]]) -> None:
    _print_section("2. Stage View - chunk-level facts")
    rows = stage_view(events)
    if not rows:
        print("  (no chunk-level events)")
        return
    for row in rows:
        print(f"\n  stage: {row['stage']}")
        print(f"    status:           {row['status']}")
        print(f"    instance_count:   {row['instance_count']}")
        print(f"    completed_count:  {row['completed_count']}")
        print(f"    failed_count:     {row['failed_count']}")
        print(f"    started_at:       {row['started_at']}")
        print(f"    completed_at:     {row['completed_at']}")
        print(f"    input_shapes:     {row['input_shapes']}")
        print(f"    output_shapes:    {row['output_shapes']}")


def _print_operation_view(events: list[dict[str, Any]]) -> None:
    _print_section("3. Operation View - business-layer facts")
    rows = operation_view(events)
    if not rows:
        print("  (no business-layer events)")
        return
    for row in rows:
        print(f"\n  event_id:   {row['event_id']}")
        print(f"    event_type: {row['event_type']}")
        print(f"    subject_id: {row['subject_id']}")
        print(f"    status:     {row['status']}")
        print(f"    timestamp:  {row['timestamp']}")
        print(f"    input:      {_to_json_str(row['input'], indent=6)}")
        print(f"    output:     {_to_json_str(row['output'], indent=6)}")
        print(f"    facts:      {_to_json_str(row['facts'], indent=6)}")
        if row.get("error"):
            print(f"    error:      {_to_json_str(row['error'], indent=6)}")


def _print_attempt_view(events: list[dict[str, Any]]) -> None:
    _print_section("4. Attempt View - model request telemetry facts")
    rows = attempt_view(events)
    if not rows:
        print("  (no model-level events)")
        return
    for row in rows:
        print(f"\n  subject_id:    {row['subject_id']}")
        print(f"    attempt_index: {row['attempt_index']}")
        print(f"    status:        {row['status']}")
        print(f"    started_at:    {row['started_at']}")
        print(f"    completed_at:  {row['completed_at']}")
        print(f"    facts:         {_to_json_str(row['facts'], indent=6)}")
        print(f"    events:        {row['events']}")
        if row.get("error"):
            print(f"    error:         {_to_json_str(row['error'], indent=6)}")


def _print_retrieval_view(events: list[dict[str, Any]]) -> None:
    _print_section("5. Retrieval View - RAG retrieval events (insurance-specific)")
    rows = retrieval_view(events)
    if not rows:
        print("  (no retrieval events)")
        return
    for row in rows:
        print(f"\n  event_id:   {row['event_id']}")
        print(f"    event_type: {row['event_type']}")
        print(f"    subject_id: {row['subject_id']}")
        print(f"    status:     {row['status']}")
        print(f"    timestamp:  {row['timestamp']}")
        facts = row.get("facts") or {}
        print(f"    query_type:           {facts.get('query_type')}")
        print(f"    candidate_count:      {facts.get('candidate_count')}")
        print(f"    packed_item_count:    {facts.get('packed_item_count')}")
        print(f"    retrieval_retry_count:{facts.get('retrieval_retry_count')}")
        print(f"    rewritten:            {facts.get('rewritten')}")
        print(f"    rewritten_query:      {facts.get('rewritten_query')}")
        if facts.get("diagnostics"):
            print(f"    diagnostics:          {_to_json_str(facts['diagnostics'], indent=6)}")


def _print_citation_view(events: list[dict[str, Any]]) -> None:
    _print_section("6. Citation View - citation/evidence events (insurance-specific)")
    rows = citation_view(events)
    if not rows:
        print("  (no citation events)")
        return
    for row in rows:
        print(f"\n  event_id:   {row['event_id']}")
        print(f"    event_type: {row['event_type']}")
        print(f"    subject_id: {row['subject_id']}")
        print(f"    status:     {row['status']}")
        print(f"    timestamp:  {row['timestamp']}")
        facts = row.get("facts") or {}
        print(f"    r2_attempt:       {facts.get('r2_attempt')}")
        print(f"    citation_count:   {facts.get('citation_count')}")
        print(f"    source_count:     {facts.get('source_count')}")
        print(f"    needs_reasoning:  {facts.get('needs_reasoning')}")
        print(f"    status:           {facts.get('status')}")
        output = row.get("output") or {}
        print(f"    answer_length:    {output.get('answer_length')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View saved Insurance RAG Agent Trace run facts",
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="run directory path (e.g. .agently/runs/insurance/traces/<task_id>)",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        print(f"Error: run directory does not exist: {run_dir}", file=sys.stderr)
        sys.exit(1)

    summary = _load_summary(run_dir)
    events = _load_events(run_dir)

    _print_run_overview(run_dir, summary)
    _print_task_view(events)
    _print_stage_view(events)
    _print_operation_view(events)
    _print_attempt_view(events)
    _print_retrieval_view(events)
    _print_citation_view(events)

    print()
    print("=" * 72)
    print(f"  Loaded {len(events)} events total")
    print("=" * 72)


if __name__ == "__main__":
    main()
