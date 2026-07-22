#!/usr/bin/env python3
"""Fase E: aggregates one or more Flight Recorder session logs
(<DATA_DIR>/audit/<session_id>.jsonl) into the UX metrics docs/UX_METRICS.md
reports on. Stdlib-only, no Aetheris install required to run it -- same
portability posture as scripts/audit_verify.py.

Metrics computed, and exactly what they're derived from:

- TTFT (time-to-first-token) per turn: `first_token.ts - turn_start.ts`.
  Requires the `first_token` entry (added specifically for this) --
  raw token deltas themselves are never logged individually.
- Turn duration: `turn_end.ts - turn_start.ts`.
- Tool calls per turn: count of `tool_call` entries between a turn's
  start/end.
- Confirm-gate approval/rejection rate + decision latency: pairs each
  `confirm_request` with the NEXT `confirm_decision` for the same tool
  (sequential by `seq` across the whole session -- a confirm_decision
  arrives via a separate HTTP request, not nested inside the turn that
  raised the confirm_request, since the backend is stateless per
  request; see agent.py's confirm_tool docstring).
- Rollback rate: count of `tool_call` entries where `payload.tool ==
  "rollback_action"`, against total approved writes.
- "Cancellation time": turns whose `turn_end.reason == "disconnected"`,
  reported as `turn_end.ts - turn_start.ts` for that turn. This is an
  HONEST APPROXIMATION, not the precise "cancel button clicked -> lock
  released" latency the original spec describes -- no `cancel_requested`
  moment is logged separately today, only the turn boundary. Documented
  as such rather than silently overstating precision (same posture as
  core/audit/egress_monitor.py's byte-count honesty).

Usage:
    python metrics_report.py <path-to-audit-dir-or-one-or-more-.jsonl-files>
    python metrics_report.py --json <same args>   # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional


def load_entries(path: Path) -> List[Dict]:
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sorted(entries, key=lambda e: e.get("seq", 0))


def _pair_turns(entries: List[Dict]) -> List[Dict]:
    """Groups entries into per-turn windows delimited by turn_start/
    turn_end pairs (in order). Entries outside any window -- e.g. a
    confirm_decision arriving from a separate HTTP request after the
    turn that raised the confirm_request already ended -- are returned
    separately as `orphan_entries` on the session dict by the caller."""
    turns = []
    current: Optional[Dict] = None
    for e in entries:
        if e["type"] == "turn_start":
            current = {"start": e, "entries": [], "end": None}
        elif current is not None:
            current["entries"].append(e)
            if e["type"] == "turn_end":
                current["end"] = e
                turns.append(current)
                current = None
    if current is not None:
        # A turn_start with no matching turn_end -- e.g. the process was
        # killed mid-turn. Kept, but ttft/duration for it will be partial.
        turns.append(current)
    return turns


def compute_metrics(entries: List[Dict]) -> Dict:
    turns = _pair_turns(entries)

    ttfts: List[float] = []
    durations: List[float] = []
    tool_calls_per_turn: List[int] = []
    cancelled_turn_durations: List[float] = []

    for turn in turns:
        start_ts = turn["start"]["ts"]
        first_token = next((e for e in turn["entries"] if e["type"] == "first_token"), None)
        if first_token is not None:
            ttfts.append(first_token["ts"] - start_ts)

        n_tool_calls = sum(1 for e in turn["entries"] if e["type"] == "tool_call")
        tool_calls_per_turn.append(n_tool_calls)

        if turn["end"] is not None:
            duration = turn["end"]["ts"] - start_ts
            durations.append(duration)
            if turn["end"]["payload"].get("reason") == "disconnected":
                cancelled_turn_durations.append(duration)

    # Confirm-gate approval/rejection + decision latency, across the
    # WHOLE session (not per-turn -- see module docstring).
    pending_requests: List[Dict] = []
    decisions: List[Dict] = []
    for e in entries:
        if e["type"] == "confirm_request":
            pending_requests.append(e)
        elif e["type"] == "confirm_decision":
            match = next((r for r in pending_requests if r["payload"].get("tool") == e["payload"].get("tool")), None)
            if match is not None:
                pending_requests.remove(match)
                decisions.append({
                    "tool": e["payload"].get("tool"),
                    "decision": e["payload"].get("decision"),
                    "decision_seconds": e["ts"] - match["ts"],
                })
            else:
                # A confirm_decision with no matching confirm_request --
                # normal for a UI-initiated action like Time-Travel
                # rollback (app.py logs confirm_decision directly, there
                # was never a confirm_request for it).
                decisions.append({"tool": e["payload"].get("tool"), "decision": e["payload"].get("decision"), "decision_seconds": None})

    approved = sum(1 for d in decisions if d["decision"] == "approved")
    declined = sum(1 for d in decisions if d["decision"] == "declined")
    decision_times = [d["decision_seconds"] for d in decisions if d["decision_seconds"] is not None]

    rollback_calls = sum(
        1 for e in entries if e["type"] == "tool_call" and e["payload"].get("tool") == "rollback_action"
    )

    def _stats(values: List[float]) -> Dict:
        if not values:
            return {"count": 0, "median": None, "mean": None, "min": None, "max": None}
        return {
            "count": len(values),
            "median": round(statistics.median(values), 3),
            "mean": round(statistics.mean(values), 3),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
        }

    return {
        "total_turns": len(turns),
        "ttft_seconds": _stats(ttfts),
        "turn_duration_seconds": _stats(durations),
        "tool_calls_per_turn": _stats([float(n) for n in tool_calls_per_turn]),
        "confirm_gate": {
            "approved": approved,
            "declined": declined,
            "approval_rate": round(approved / (approved + declined), 3) if (approved + declined) else None,
            "decision_seconds": _stats(decision_times),
        },
        "rollback": {
            "count": rollback_calls,
            "rate_vs_approved_writes": round(rollback_calls / approved, 3) if approved else None,
        },
        "cancelled_turns": {
            "count": len(cancelled_turn_durations),
            "duration_seconds": _stats(cancelled_turn_durations),
            "note": "turn_start-to-turn_end for disconnected turns -- an approximation of "
                    "cancel latency, not a precise cancel-click-to-stop measurement (no "
                    "separate cancel_requested marker is logged today).",
        },
    }


def _print_human(session_id: str, metrics: Dict) -> None:
    print(f"\n=== {session_id} ===")
    print(f"Turns: {metrics['total_turns']}")
    t = metrics["ttft_seconds"]
    print(f"TTFT (s): median={t['median']} mean={t['mean']} min={t['min']} max={t['max']} (n={t['count']})")
    d = metrics["turn_duration_seconds"]
    print(f"Turn duration (s): median={d['median']} mean={d['mean']} (n={d['count']})")
    tc = metrics["tool_calls_per_turn"]
    print(f"Tool calls/turn: median={tc['median']} mean={tc['mean']}")
    cg = metrics["confirm_gate"]
    print(f"Confirm gate: {cg['approved']} approved, {cg['declined']} declined "
          f"(approval rate={cg['approval_rate']}), decision time median={cg['decision_seconds']['median']}s")
    rb = metrics["rollback"]
    print(f"Rollback: {rb['count']} calls (rate vs approved writes={rb['rate_vs_approved_writes']})")
    ct = metrics["cancelled_turns"]
    print(f"Cancelled turns: {ct['count']} (duration median={ct['duration_seconds']['median']}s) -- {ct['note']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate Flight Recorder logs into UX metrics.")
    parser.add_argument("paths", nargs="+", help="One or more .jsonl session logs, or a directory containing them.")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output instead of the human summary.")
    args = parser.parse_args()

    files: List[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.glob("*.jsonl")))
        elif p.is_file():
            files.append(p)

    if not files:
        print("No .jsonl session logs found.", file=sys.stderr)
        sys.exit(1)

    results = {}
    for f in files:
        entries = load_entries(f)
        if not entries:
            continue
        results[f.stem] = compute_metrics(entries)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for session_id, metrics in results.items():
            _print_human(session_id, metrics)


if __name__ == "__main__":
    main()
