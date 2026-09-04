#!/usr/bin/env python3
"""Track the four-hour Qwen3-VL compatibility decision gate."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_PATH = Path("artifacts/model-compatibility-gate.json")
PRIMARY = "Qwen/Qwen3-VL-8B-Instruct"
FALLBACK = "Qwen/Qwen2.5-VL-7B-Instruct"
WINDOW = timedelta(hours=4)


def load_state() -> dict:
    if not STATE_PATH.exists():
        raise SystemExit("Gate has not started. Run: python3 scripts/model_gate.py start")
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def now() -> datetime:
    return datetime.now(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    start_parser = sub.add_parser("start")
    start_parser.add_argument("--model", default=PRIMARY)

    record_parser = sub.add_parser("record")
    record_parser.add_argument("--result", choices=("pass", "fail"), required=True)
    record_parser.add_argument("--reason", required=True)

    sub.add_parser("status")
    args = parser.parse_args()

    if args.command == "start":
        if STATE_PATH.exists():
            state = load_state()
            print("Gate already started; existing start time is preserved.")
        else:
            started = now()
            state = {
                "primary_model": args.model,
                "fallback_model": FALLBACK,
                "started_at_utc": started.isoformat(),
                "deadline_at_utc": (started + WINDOW).isoformat(),
                "attempts": [],
                "status": "running",
            }
            save_state(state)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    state = load_state()
    if args.command == "record":
        state["attempts"].append(
            {
                "recorded_at_utc": now().isoformat(),
                "result": args.result,
                "reason": args.reason,
            }
        )
        if args.result == "pass":
            state["status"] = "passed"
        save_state(state)

    started = datetime.fromisoformat(state["started_at_utc"])
    deadline = datetime.fromisoformat(state["deadline_at_utc"])
    current = now()
    elapsed = current - started
    timed_out = current >= deadline and state.get("status") != "passed"
    if timed_out:
        state["status"] = "fallback_required"
        save_state(state)

    summary = {
        **state,
        "checked_at_utc": current.isoformat(),
        "elapsed_seconds": int(elapsed.total_seconds()),
        "remaining_seconds": max(0, int((deadline - current).total_seconds())),
        "decision": (
            f"Switch to {FALLBACK}"
            if timed_out
            else "Continue current model compatibility tests"
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if timed_out else 0


if __name__ == "__main__":
    raise SystemExit(main())
