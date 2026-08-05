#!/usr/bin/env python3
"""determinex_knowledge_query.py -- fast, deterministic complement to determinex_ask.py.

determinex_ask.py routes freeform questions through the local 7B Sentinel model
(RAG + WAL + git context) -- powerful but slow (multi-minute on CPU) and only
as good as the model's reasoning that session.
determinex_rag_index.py needs a Postgres DB that was never provisioned -- dead.
determinex_code_rag.py needs a symbol index that was never built -- dead.

This tool is the fourth option: instant, no model call, no DB. It searches
build_knowledge.json directly -- the 72 dated findings blobs plus the
_topic_index consolidation layer added 2026-06-30 -- and answers live
ProgramBench status questions straight from eval_index.json / the board.
Use this for "what do we already know about X" and quick status checks;
use determinex_ask.py when you need actual reasoning over the answer.

Usage:
  python scripts/determinex_knowledge_query.py "provenance gaming"        # keyword search
  python scripts/determinex_knowledge_query.py --topics                   # list topic buckets
  python scripts/determinex_knowledge_query.py --topic ORACLE_MECHANICS   # one bucket
  python scripts/determinex_knowledge_query.py --key luajit_vmdef_wall_2026_06_23
  python scripts/determinex_knowledge_query.py --status                   # live PB score snapshot
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "corpus" / "programbench" / "build_knowledge.json"
EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"
BOARD = ROOT / "logs" / "programbench_lock_board.json"


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_topics() -> int:
    d = _load(KNOWLEDGE)
    idx = d.get("_topic_index", {})
    if not idx:
        print("No _topic_index found -- run the consolidation pass first.")
        return 1
    for cat, items in sorted(idx.items(), key=lambda x: -len(x[1])):
        print(f"{cat:24s} {len(items):3d} findings")
    return 0


def cmd_topic(name: str) -> int:
    d = _load(KNOWLEDGE)
    idx = d.get("_topic_index", {})
    items = idx.get(name)
    if items is None:
        print(f"Unknown topic '{name}'. Known: {sorted(idx)}")
        return 1
    for it in items:
        print(f"[{it['key']}]")
        print(f"  {it['summary']}")
    return 0


def cmd_key(key: str) -> int:
    d = _load(KNOWLEDGE)
    if key not in d:
        print(f"No key '{key}' in build_knowledge.json")
        return 1
    print(json.dumps(d[key], indent=2, ensure_ascii=False))
    return 0


def cmd_search(query: str) -> int:
    d = _load(KNOWLEDGE)
    terms = [t.lower() for t in query.split()]
    hits: list[tuple[int, str, str]] = []
    for key, val in d.items():
        if key.startswith("_"):
            continue
        blob = (key + " " + json.dumps(val, ensure_ascii=False)).lower()
        score = sum(blob.count(t) for t in terms)
        if score:
            doc = (
                val.get("_doc") if isinstance(val, dict) else (val if isinstance(val, str) else "")
            )
            hits.append((score, key, (doc or "")[:200]))
    hits.sort(reverse=True)
    if not hits:
        print(f"No matches for: {query}")
        return 1
    for score, key, doc in hits[:15]:
        print(f"[{score:3d}] {key}")
        if doc:
            print(f"       {doc}")
    print(f"\n{len(hits)} total matches. Use --key <name> for full content.")
    return 0


def cmd_status() -> int:
    ei = _load(EVAL_INDEX)
    locked = [r for r in ei if r.get("official_full_suite_resolved") and not r.get("alias_for")]
    ceilings = [
        r
        for r in ei
        if r.get("status") in ("ceiling_certified", "ceiling_confirmed") and not r.get("alias_for")
    ]
    print(f"ProgramBench official locks: {len(locked)}/200 = {len(locked) / 200 * 100:.1f}%")
    print(f"Ceiling-certified: {len(ceilings)}")
    if BOARD.exists():
        board = _load(BOARD)
        remaining = [r for r in board if not r.get("locked_archive")]
        print(f"Board: {len(board)} total rows, {len(remaining)} remaining (not locked_archive)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("query", nargs="?", help="keyword search terms")
    p.add_argument("--topics", action="store_true", help="list all topic buckets")
    p.add_argument("--topic", help="list findings under one topic bucket")
    p.add_argument("--key", help="print full content of one build_knowledge.json key")
    p.add_argument("--status", action="store_true", help="live PB score snapshot")
    args = p.parse_args(argv)

    if args.status:
        return cmd_status()
    if args.topics:
        return cmd_topics()
    if args.topic:
        return cmd_topic(args.topic)
    if args.key:
        return cmd_key(args.key)
    if args.query:
        return cmd_search(args.query)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
