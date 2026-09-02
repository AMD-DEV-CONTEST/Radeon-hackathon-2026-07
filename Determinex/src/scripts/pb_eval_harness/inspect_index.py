#!/usr/bin/env python3
"""Quick inspection of eval_index.json for harness planning."""

import json
import pathlib

ROOT = pathlib.Path(__file__).parent.parent.parent
INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"

data = json.loads(INDEX.read_text(encoding="utf-8"))

pending = sorted(
    [d for d in data if d["status"] == "pending_unlock"],
    key=lambda x: -x.get("official_score_pct", 0),
)
board = sorted(
    [d for d in data if d["status"] == "board_cache_only"],
    key=lambda x: -x.get("official_score_pct", 0),
)
strict = [d for d in data if d["status"] in ("strict_lock", "upstream_skips")]

print("=== PENDING UNLOCK ===")
for d in pending:
    ep = d.get("eval_report_path", "")
    has_sub = False
    if ep:
        p = pathlib.Path(ep).parent
        has_sub = (p / "submission.tar.gz").exists()
    slug = d["slug"]
    pct = d.get("official_score_pct", 0)
    passed = d.get("official_passed", 0)
    total = d.get("official_total", 0)
    not_run = d.get("official_not_run", 0)
    print(f"  {slug}: {pct:.1f}% ({passed}/{total}) not_run={not_run} sub={has_sub}")

print(f"\n=== BOARD CACHE ({len(board)}) - top 40 ===")
for d in board[:40]:
    slug = d["slug"]
    pct = d.get("official_score_pct", 0)
    passed = d.get("official_passed", 0)
    total = d.get("official_total", 0)
    print(f"  {slug}: {pct:.1f}% ({passed}/{total})")

print(f"\n=== STRICT LOCKS ({len(strict)}) ===")
for d in strict:
    print(f"  {d['slug']}: {d['status']}")
