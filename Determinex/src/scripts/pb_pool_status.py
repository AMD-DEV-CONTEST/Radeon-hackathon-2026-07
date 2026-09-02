#!/usr/bin/env python3
"""Render a transparent ProgramBench local/Hetzner drain-pool status report."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from determinex_atomic_io import (  # noqa: E402
    load_json_with_retry as load,
)
from determinex_atomic_io import (
    write_json_atomic,
    write_text_atomic,
)

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "logs" / "programbench_lock_board.json"
QUEUE = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_QUEUE.json"
RES = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_RESERVATIONS.json"
OUT_MD = ROOT / "logs" / "programbench_factory" / "POOL_STATUS.md"
OUT_JSON = ROOT / "logs" / "programbench_factory" / "POOL_STATUS.json"
PY = Path(sys.executable)


def capture(cmd: list[str]) -> str:
    try:
        return subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
        ).stdout
    except Exception as exc:
        return f"ERROR: {exc}"


def active_local() -> list[dict[str, str]]:
    text = capture(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"])
    rows = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            rows.append({"name": parts[0], "status": parts[1], "image": parts[2]})
    return rows


def main() -> int:
    # Refresh queue first so statuses/reservations are current.
    subprocess.run(
        [str(PY), str(ROOT / "scripts" / "pb_native_eval_queue.py"), "--top", "1"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
    )

    board = load(BOARD, [])
    queue = load(QUEUE, [])
    reservations = load(RES, {})
    local = active_local()

    locked = [r for r in board if float(r.get("best_score") or 0) >= 100]
    q_counts = Counter(r["status"] for r in queue)
    board_bases = {r["base_slug"] for r in board if r.get("base_slug")}
    queue_bases = {r["base_slug"] for r in queue}
    missing = [
        r
        for r in board
        if float(r.get("best_score") or 0) < 100 and r.get("base_slug") not in queue_bases
    ]

    active_slugs = []
    for row in local:
        img = row["image"]
        if "/" in img:
            active_slugs.append(img.split("/")[-1].split(":")[0].replace("_1776_", "__"))

    report = {
        "board_rows": len(board),
        "unique_board_bases": len(board_bases),
        "locked_100": len(locked),
        "remaining_to_200": 200 - len(locked),
        "queue_counts": dict(q_counts),
        "reservations_entries": len(reservations),
        "local_active": local,
        "local_active_slugish": active_slugs,
        "missing_not_pooled_count": len(missing),
        "missing_top": [
            {
                "base_slug": r["base_slug"],
                "score": float(r.get("best_score") or 0),
                "passed": int(r.get("best_passed") or 0),
                "total": int(r.get("best_runnable_total") or 0),
            }
            for r in sorted(missing, key=lambda x: -float(x.get("best_score") or 0))[:40]
        ],
    }
    write_json_atomic(OUT_JSON, report)

    lines = [
        "# ProgramBench Drain Pool Status",
        "",
        f"- board rows: {report['board_rows']}",
        f"- unique board bases: {report['unique_board_bases']}",
        f"- locked 100: {report['locked_100']}",
        f"- remaining to canonical 200: {report['remaining_to_200']}",
        f"- reservations entries: {report['reservations_entries']}",
        f"- missing/not-pooled: {report['missing_not_pooled_count']}",
        "",
        "## Queue Counts",
        "",
    ]
    for k, v in sorted(q_counts.items()):
        lines.append(f"- {k}: {v}")
    lines += ["", "## Local Active", ""]
    for row in local:
        lines.append(f"- {row['image']} ({row['status']})")
    lines += [
        "",
        "## Missing / Not Pooled Top 40",
        "",
        "| score | passed/total | tool |",
        "|---:|---:|---|",
    ]
    for r in report["missing_top"]:
        lines.append(f"| {r['score']:.2f} | {r['passed']}/{r['total']} | {r['base_slug']} |")
    write_text_atomic(OUT_MD, "\n".join(lines) + "\n")
    print(OUT_MD)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "locked_100",
                    "remaining_to_200",
                    "queue_counts",
                    "missing_not_pooled_count",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
