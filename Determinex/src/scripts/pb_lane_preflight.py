#!/usr/bin/env python3
"""ProgramBench lane preflight.

Build a launch queue that excludes no-op reruns:

- override identical to v1 baseline source -> needs code change
- override identical to current board-best source -> needs code change
- override differs from baseline and board-best source -> launchable

This is intentionally mechanical. It does not decide what to implement; it
prevents wasting Docker lanes on byte-identical submissions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
BOARD = ROOT / "logs" / "programbench_lock_board.json"
FACTORY = ROOT / "logs" / "programbench_factory"
BLOCKLIST = FACTORY / "lane_blocklist.json"
V1_ROOT = Path("T:/determinex-programbench")


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(value: str | None) -> str:
    return value[:12] if value else ""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def accepted_slugs() -> set[str]:
    path = FACTORY / "accepted_runs.jsonl"
    out: set[str] = set()
    if not path.is_file():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                slug = json.loads(line).get("slug")
            except json.JSONDecodeError:
                continue
            if slug:
                out.add(slug)
    return out


def blocklist() -> dict[str, str]:
    if not BLOCKLIST.is_file():
        return {}
    try:
        data = json.loads(BLOCKLIST.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def latest_eval_for_run(run_root: str | None) -> Path | None:
    if not run_root:
        return None
    root = Path(run_root)
    if not root.is_absolute():
        root = ROOT / root
    if not root.is_dir():
        return None
    evals = sorted(root.rglob("*.eval.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return evals[0] if evals else None


@dataclass
class Row:
    status: str
    slug: str
    score: float
    passed: int
    runnable: int
    reason: str
    override_hash: str
    baseline_hash: str
    best_hash: str
    accepted_before: bool
    run_root: str
    next_action: str


def classify(row: dict[str, Any], accepted: set[str], blocked: dict[str, str]) -> Row | None:
    slug = row.get("slug") or ""
    if not slug:
        return None

    override_main = OVERRIDES / slug / "main.py"
    baseline_main = V1_ROOT / f"determinex_pb_factory_{slug}_v1" / slug / "source" / "main.py"
    if not override_main.is_file():
        return None

    override_hash = sha256(override_main)
    baseline_hash = sha256(baseline_main)

    best_hash = None
    run_root = row.get("run_root") or ""
    if run_root:
        rr = Path(run_root)
        if not rr.is_absolute():
            rr = ROOT / rr
        best_main = rr / slug / "source" / "main.py"
        best_hash = sha256(best_main)

    score = float(row.get("best_score") or 0.0)
    passed = int(row.get("best_passed") or 0)
    runnable = int(row.get("best_runnable_total") or 0)
    next_action = str(row.get("next_action") or "")
    was_accepted = slug in accepted

    if slug in blocked:
        status = "NEEDS_CODE_CHANGE"
        reason = blocked[slug]
    elif score >= 100.0:
        status = "SKIP_LOCKED"
        reason = "already 100"
    elif baseline_hash and override_hash == baseline_hash:
        status = "NEEDS_CODE_CHANGE"
        reason = "override byte-identical to v1 baseline source"
    elif best_hash and override_hash == best_hash:
        status = "NEEDS_CODE_CHANGE"
        reason = "override byte-identical to current board-best source"
    elif was_accepted and best_hash and override_hash == best_hash:
        status = "NEEDS_CODE_CHANGE"
        reason = "accepted source already reflected in board"
    else:
        status = "LAUNCHABLE"
        reason = "override differs from baseline/current best"

    return Row(
        status=status,
        slug=slug,
        score=score,
        passed=passed,
        runnable=runnable,
        reason=reason,
        override_hash=short_hash(override_hash),
        baseline_hash=short_hash(baseline_hash),
        best_hash=short_hash(best_hash),
        accepted_before=was_accepted,
        run_root=run_root,
        next_action=next_action,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score-max", type=float, default=50.0)
    ap.add_argument("--min-runnable", type=int, default=200)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--status", default="LAUNCHABLE")
    ap.add_argument(
        "--write",
        action="store_true",
        help="write JSON/CSV reports under logs/programbench_factory",
    )
    args = ap.parse_args()

    board = load_json(BOARD)
    accepted = accepted_slugs()
    blocked = blocklist()
    rows: list[Row] = []
    for item in board:
        runnable = int(item.get("best_runnable_total") or 0)
        score = float(item.get("best_score") or 0.0)
        if runnable < args.min_runnable or score > args.score_max:
            continue
        classified = classify(item, accepted, blocked)
        if classified:
            rows.append(classified)

    rows.sort(key=lambda r: (r.status != "LAUNCHABLE", r.score, -r.runnable, r.slug))
    selected = [r for r in rows if args.status == "ALL" or r.status == args.status][: args.limit]

    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1

    print("status counts:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print()
    print(f"{'status':18} {'score':>7} {'passed':>7} {'run':>6}  slug")
    for r in selected:
        print(f"{r.status:18} {r.score:7.2f} {r.passed:7d} {r.runnable:6d}  {r.slug}  # {r.reason}")

    if args.write:
        FACTORY.mkdir(parents=True, exist_ok=True)
        json_path = FACTORY / "lane_preflight.json"
        csv_path = FACTORY / "lane_preflight.csv"
        json_path.write_text(json.dumps([asdict(r) for r in rows], indent=2), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=list(asdict(rows[0]).keys()) if rows else ["status"]
            )
            writer.writeheader()
            for r in rows:
                writer.writerow(asdict(r))
        print()
        print(f"wrote {json_path}")
        print(f"wrote {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
