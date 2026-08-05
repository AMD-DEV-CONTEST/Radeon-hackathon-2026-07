#!/usr/bin/env python3
"""Build a repair queue from corpus hint-audit reject notes.

The queue is intentionally advisory. It does not modify overrides, pack
candidates, reserve workers, or deploy shards. It ranks rejected/non-lock tools
whose hint audit produced a specific next action.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "corpus" / "programbench" / "training_corpus" / "reject_notes"
BOARD = ROOT / "logs" / "programbench_lock_board.json"
OUT_JSON = ROOT / "logs" / "programbench_factory" / "HINT_REPAIR_QUEUE.json"
OUT_MD = ROOT / "logs" / "programbench_factory" / "HINT_REPAIR_QUEUE.md"

PRIORITY_SCORE = {"high": 300, "medium": 200, "low": 100}
STATUS_PENALTY = {
    "locked": -10000,
    "gated:accept": -30,
    "gated:reject": 0,
    "evaluated": 25,
}


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _iter_latest_notes() -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not NOTES.is_dir():
        return latest
    for path in NOTES.glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            slug = rec.get("slug") or path.stem
            old = latest.get(slug)
            if old is None or str(rec.get("captured_at", "")) >= str(old.get("captured_at", "")):
                latest[slug] = rec
    return latest


def _board_maps() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = _load_json(BOARD, [])
    by_slug = {r.get("slug"): r for r in rows if r.get("slug")}
    by_base = {r.get("base_slug"): r for r in rows if r.get("base_slug")}
    return by_slug, by_base


def _status(row: dict[str, Any]) -> str:
    if row.get("best_runnable_total") and row.get("best_passed") == row.get("best_runnable_total"):
        return "locked"
    return str(row.get("status") or row.get("queue_status") or row.get("gate_status") or "")


def _score(note: dict[str, Any], board_row: dict[str, Any]) -> int:
    pri = str(note.get("requeue_priority") or "low")
    base = PRIORITY_SCORE.get(pri, 0)
    status = _status(board_row)
    base += STATUS_PENALTY.get(status, 0)
    try:
        base += int(float(board_row.get("best_score") or board_row.get("score") or 0))
    except Exception:
        pass
    if "new behavior class" in str(note.get("likely_cause", "")).lower():
        base -= 50
    if not note.get("next_action"):
        base -= 25
    return base


def _rule_b_floor_note(note: dict[str, Any], board_row: dict[str, Any]) -> dict[str, Any]:
    """Prefer fresh floor discoveries over stale reject hints.

    A Rule B accept is not a lock, but it is more current than the reject note
    that led to the patch. The next action should be promotion work, not
    re-fixing the old rejected pattern.
    """
    floor = board_row.get("rule_b_discovery")
    if not isinstance(floor, dict):
        return note
    floor_ts = str(floor.get("captured_at") or "")
    note_ts = str(note.get("captured_at") or "")
    floor_key = "".join(ch for ch in floor_ts if ch.isdigit())
    note_key = "".join(ch for ch in note_ts if ch.isdigit())
    if floor_key and note_key and floor_key < note_key:
        return note
    passed = floor.get("passed")
    runnable = floor.get("runnable_total")
    out = dict(note)
    out.update(
        {
            "requeue_priority": "high",
            "likely_cause": "accepted floor raise awaiting strict promotion",
            "next_action": (
                f"Run a clean Rule A re-gate from the accepted floor "
                f"({passed}/{runnable}) before further pattern tuning."
            ),
            "matched_patterns": ["rule_b_floor"],
            "hook_status": {
                "rule_b_discovery": "present",
                "captured_at": floor_ts,
            },
            "captured_at": floor_ts or note_ts,
        }
    )
    return out


def build_queue(limit: int) -> list[dict[str, Any]]:
    by_slug, by_base = _board_maps()
    out: list[dict[str, Any]] = []
    for slug, note in _iter_latest_notes().items():
        base_slug = slug.rsplit(".", 1)[0]
        board_row = by_slug.get(slug) or by_base.get(base_slug) or {}
        status = _status(board_row)
        if status == "locked":
            continue
        note = _rule_b_floor_note(note, board_row)
        floor = board_row.get("rule_b_discovery") or {}
        row = {
            "slug": slug,
            "base_slug": base_slug,
            "priority": note.get("requeue_priority") or "low",
            "rank_score": _score(note, board_row),
            "board_score": board_row.get("best_score") or board_row.get("score"),
            "passed": floor.get("passed")
            or board_row.get("best_passed")
            or board_row.get("passed"),
            "runnable": floor.get("runnable_total")
            or board_row.get("best_runnable_total")
            or board_row.get("runnable"),
            "status": status,
            "likely_cause": note.get("likely_cause") or "",
            "next_action": note.get("next_action") or "",
            "matched_patterns": note.get("matched_patterns") or [],
            "hook_status": note.get("hook_status") or {},
            "captured_at": note.get("captured_at") or "",
        }
        out.append(row)
    out.sort(key=lambda r: (-int(r["rank_score"]), str(r["slug"])))
    return out[:limit]


def write_outputs(rows: list[dict[str, Any]]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Hint Repair Queue",
        "",
        "Ranked from latest corpus hint-audit reject notes. Use this to pick targeted repairs before blind queue export.",
        "",
        "| Rank | Priority | Score | Tool | Board | Cause | Next action |",
        "|---:|---|---:|---|---:|---|---|",
    ]
    for i, row in enumerate(rows, 1):
        board = ""
        if row.get("passed") is not None and row.get("runnable") is not None:
            board = f"{row['passed']}/{row['runnable']}"
        cause = str(row["likely_cause"]).replace("|", "\\|")
        action = str(row["next_action"]).replace("|", "\\|")
        lines.append(
            f"| {i} | {row['priority']} | {row['rank_score']} | `{row['slug']}` | {board} | {cause} | {action} |"
        )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    rows = build_queue(args.limit)
    write_outputs(rows)
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    counts = Counter(str(r["priority"]) for r in rows)
    print("priority:", dict(counts))
    for row in rows[:15]:
        print(
            f"{row['rank_score']:>4} {row['priority']:<6} {row['slug']} :: {row['likely_cause']} -> {row['next_action']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
