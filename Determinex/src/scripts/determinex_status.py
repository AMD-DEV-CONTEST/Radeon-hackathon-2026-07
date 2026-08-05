"""scripts/determinex_status.py — Live and historical pipeline event viewer.

Reads the structured JSONL event log written by scripts/observability/event_logger.py
and renders a human-readable status display.

Usage:
    python scripts/determinex_status.py                  # today's events, last 50
    python scripts/determinex_status.py --last-run       # events from the most recent session
    python scripts/determinex_status.py --tail           # live follow (Ctrl+C to stop)
    python scripts/determinex_status.py --tail -n 20     # seed with last 20 then live
    python scripts/determinex_status.py --date 2026-05-25  # a specific day's log
    python scripts/determinex_status.py --json           # raw JSON lines (no formatting)
    python scripts/determinex_status.py --summary        # session summary (counts per event type)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_DEFAULT_AUDIT_DIR = Path(os.environ.get("DETERMINEX_AUDIT_DIR", "T:/determinex_audit/events"))
_FALLBACK_AUDIT_DIR = REPO_ROOT / "logs" / "events"


# ---------------------------------------------------------------------------
# Log file discovery
# ---------------------------------------------------------------------------


def _audit_dir() -> Path:
    for d in (_DEFAULT_AUDIT_DIR, _FALLBACK_AUDIT_DIR):
        if d.exists():
            return d
    return _FALLBACK_AUDIT_DIR


def _log_path(date_str: str | None = None) -> Path:
    if date_str is None:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    return _audit_dir() / f"{date_str}.jsonl"


def _all_log_paths() -> list[Path]:
    d = _audit_dir()
    return sorted(d.glob("*.jsonl"))


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------


def _parse_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _iter_log(path: Path) -> Iterator[dict]:
    if not path.is_file():
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            evt = _parse_line(line)
            if evt:
                yield evt


def _iter_all_logs() -> Iterator[dict]:
    for p in _all_log_paths():
        yield from _iter_log(p)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_EMOJI: dict[str, str] = {
    # lifecycle
    "task.accepted": "▶",
    "task.denied": "✗",
    # baseline
    "baseline.started": "·",
    "baseline.completed": "✓",
    "baseline.failed": "✗",
    # mutation
    "mutation.created": "~",
    "mutation.skipped": "·",
    # repair
    "repair.started": "⚙",
    "repair.completed": "✓",
    "repair.failed": "✗",
    # verifier
    "verifier.started": "·",
    "verifier.completed": "✓",
    "verifier.timeout": "⏱",
    # corpus
    "corpus.row_written": "💾",
    "corpus.row_rejected": "✗",
    "corpus.signed": "🔐",
    "corpus.signature_failed": "✗",
    # cloak
    "cloak.applied": "🔒",
    "cloak.failed": "✗",
    "cloak.audit_logged": "📋",
    # gates
    "gate.license_rejected": "⚠",
    "gate.safety_blocked": "🛑",
    "gate.mutation_skipped": "·",
    # schema
    "schema.validated": "✓",
    "schema.migrated": "↑",
    "schema.rejected": "✗",
    # swebench
    "swebench.patch_generated": "✓",
    "swebench.patch_failed": "✗",
    "swebench.cloak_applied": "🔒",
    "swebench.cloak_failed": "✗",
    "swebench.worktree_created": "·",
    "swebench.worktree_cleaned": "·",
    # programbench
    "pb.task_started": "▶",
    "pb.task_completed": "✓",
    "pb.task_failed": "✗",
    "pb.gate_accepted": "🔓",
    "pb.gate_rejected": "✗",
}

_SUCCESS_EVENTS = {
    "task.accepted",
    "baseline.completed",
    "repair.completed",
    "verifier.completed",
    "corpus.row_written",
    "corpus.signed",
    "cloak.applied",
    "schema.validated",
    "schema.migrated",
    "swebench.patch_generated",
    "swebench.cloak_applied",
    "pb.task_completed",
    "pb.gate_accepted",
}
_FAILURE_EVENTS = {
    "task.denied",
    "baseline.failed",
    "repair.failed",
    "verifier.timeout",
    "corpus.row_rejected",
    "corpus.signature_failed",
    "cloak.failed",
    "gate.license_rejected",
    "gate.safety_blocked",
    "schema.rejected",
    "swebench.patch_failed",
    "swebench.cloak_failed",
    "pb.task_failed",
    "pb.gate_rejected",
}


def _fmt_ts(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return ts[:8] if ts else "??:??:??"


def _fmt_event(evt: dict, wide: bool = False) -> str:
    etype = evt.get("event_type", "unknown")
    marker = _EMOJI.get(etype, "·")
    ts = _fmt_ts(evt.get("timestamp", ""))
    task_id = evt.get("task_id", "")[:16]
    lang = evt.get("language", "")
    result = evt.get("result", "")
    reason = evt.get("reason", "")
    duration = evt.get("duration_ms", 0.0)

    parts = [f"{ts}", f"{marker}", f"{etype:<35}"]
    if task_id:
        parts.append(f"task={task_id}")
    if lang:
        parts.append(f"lang={lang}")
    if result:
        parts.append(f"result={result}")
    if reason and wide:
        parts.append(f"reason={reason[:60]}")
    if duration and duration > 0:
        if duration >= 1000:
            parts.append(f"{duration / 1000:.1f}s")
        else:
            parts.append(f"{duration:.0f}ms")

    return "  ".join(parts)


# ---------------------------------------------------------------------------
# Session grouping
# ---------------------------------------------------------------------------


def _find_last_run_events(events: list[dict]) -> list[dict]:
    """Return events from the most recent session boundary.

    A session is a contiguous run of events sharing a session_id.
    If no session_id is recorded, fall back to the last 'task.accepted' group.
    """
    if not events:
        return []

    # Try session_id grouping
    session_ids = [e.get("session_id", "") for e in events if e.get("session_id")]
    if session_ids:
        last_sid = session_ids[-1]
        run = [e for e in events if e.get("session_id") == last_sid]
        if run:
            return run

    # Fallback: find last task.accepted boundary and take everything after
    last_task_idx = None
    for i, evt in enumerate(events):
        if evt.get("event_type") == "task.accepted":
            last_task_idx = i
    if last_task_idx is not None:
        return events[last_task_idx:]

    return events[-50:]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _render_summary(events: list[dict]) -> str:
    counts: dict[str, int] = {}
    for e in events:
        etype = e.get("event_type", "unknown")
        counts[etype] = counts.get(etype, 0) + 1

    total = len(events)
    written = counts.get("corpus.row_written", 0)
    rejected = counts.get("corpus.row_rejected", 0)
    failures = sum(counts.get(k, 0) for k in _FAILURE_EVENTS)

    lines = [
        f"  total events : {total}",
        f"  corpus written: {written}",
        f"  corpus rejected: {rejected}",
        f"  pipeline failures: {failures}",
        "",
        "  event breakdown:",
    ]
    for etype, count in sorted(counts.items(), key=lambda x: -x[1]):
        marker = _EMOJI.get(etype, "·")
        lines.append(f"    {marker} {etype:<40} {count:>5}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tail mode
# ---------------------------------------------------------------------------


def _tail_follow(path: Path, seed_lines: int = 50, raw: bool = False) -> None:
    """Live tail the JSONL file. Ctrl+C to exit."""
    # Seed with the last N lines already in the file
    existing: list[dict] = []
    if path.is_file():
        with open(path, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        for line in all_lines[-seed_lines:]:
            evt = _parse_line(line)
            if evt:
                existing.append(evt)
        offset = path.stat().st_size
    else:
        offset = 0

    for evt in existing:
        if raw:
            print(json.dumps(evt))
        else:
            print(_fmt_event(evt, wide=True))

    print(f"  --- tailing {path} (Ctrl+C to stop) ---")

    try:
        while True:
            if not path.is_file():
                time.sleep(1)
                continue
            size = path.stat().st_size
            if size > offset:
                with open(path, encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    new_data = f.read()
                offset = size
                for line in new_data.splitlines():
                    evt = _parse_line(line)
                    if evt:
                        if raw:
                            print(json.dumps(evt))
                        else:
                            print(_fmt_event(evt, wide=True))
                        sys.stdout.flush()
            # Switch to next day's file if date rolled over
            today_path = _log_path()
            if today_path != path and today_path.is_file():
                print(f"  --- date rollover → {today_path} ---")
                path = today_path
                offset = 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--last-run", action="store_true", help="show only events from the most recent session"
    )
    ap.add_argument("--tail", action="store_true", help="live follow mode (Ctrl+C to stop)")
    ap.add_argument("--date", default=None, help="specific date log to read (YYYY-MM-DD)")
    ap.add_argument(
        "-n",
        "--lines",
        type=int,
        default=50,
        help="number of lines to show (default: 50; in --tail: seed count)",
    )
    ap.add_argument("--json", action="store_true", help="output raw JSON lines")
    ap.add_argument("--summary", action="store_true", help="show per-event-type counts")
    ap.add_argument("--all", action="store_true", help="read all log files across all dates")
    args = ap.parse_args()

    if args.tail:
        path = _log_path(args.date)
        _tail_follow(path, seed_lines=args.lines, raw=args.json)
        return 0

    # Static mode: load events
    if args.all:
        events = list(_iter_all_logs())
    else:
        path = _log_path(args.date)
        events = list(_iter_log(path))
        if not events and args.date is None:
            # Today's log empty or missing — show yesterday's if available
            all_paths = _all_log_paths()
            if all_paths:
                events = list(_iter_log(all_paths[-1]))
                if events:
                    print(f"  (today's log empty; showing {all_paths[-1].name})")

    if not events:
        d = _audit_dir()
        print(f"No events found. Audit dir: {d}")
        if not d.exists():
            print("  (directory does not exist — run any pipeline task to start logging)")
        return 0

    if args.last_run:
        events = _find_last_run_events(events)

    if not args.summary:
        display = events[-args.lines :] if not args.last_run else events
        for evt in display:
            if args.json:
                print(json.dumps(evt))
            else:
                print(_fmt_event(evt, wide=True))
        print(f"\n  {len(display)} event(s) shown  ({len(events)} total in log)")

    if args.summary:
        print(_render_summary(events))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
