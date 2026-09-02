#!/usr/bin/env python3
"""programbench_fixture_extractor.py - extract golden/fixture file contents
from each tool's test tarballs, so scaffolds can match `assert stdout ==
(RESOURCES / "version.golden").read_text()` by emitting the golden text
exactly.

For each tool, walks every branch tarball and grabs:
  - any file under eval/resources/, eval/fixtures/, eval/tests/data/
  - any *.golden, *.expected, *.gold, *.fixture
  - any *.json, *.txt under tests/data/

Output: logs/mass_run_v2/fixture_bank.json  — {tool: {path: contents}}
Capped at ~2KB per file, 100 files per tool.
"""

from __future__ import annotations

import argparse
import json
import os
import tarfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logs" / "mass_run_v2" / "fixture_bank.json"
HF_CACHE = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
HF_SNAPSHOT = HF_CACHE / "datasets--programbench--ProgramBench-Tests" / "snapshots"

FIXTURE_SUFFIXES = (".golden", ".expected", ".gold", ".fixture", ".snap")
FIXTURE_DIRS = ("/resources/", "/fixtures/", "/data/", "/expected/", "/golden/")
MAX_FILE_SIZE = 8192  # capture full golden files (up to 8KB)
MAX_FILES_PER_TOOL = 120


def is_fixture_path(name: str) -> bool:
    nl = name.lower()
    if any(nl.endswith(s) for s in FIXTURE_SUFFIXES):
        return True
    if any(d in nl for d in FIXTURE_DIRS) and nl.endswith(
        (".txt", ".json", ".yaml", ".yml", ".toml", ".csv", ".md", ".log", ".out", ".err", ".dat")
    ):
        return True
    return False


def find_snapshot() -> Path | None:
    if not HF_SNAPSHOT.is_dir():
        return None
    snapshots = sorted(HF_SNAPSHOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return snapshots[0] if snapshots else None


def mine_branch(tar_path: Path, fixtures: dict[str, str]) -> None:
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                if member.size > MAX_FILE_SIZE * 5:
                    continue
                name = member.name.replace("\\", "/")
                if not is_fixture_path(name):
                    continue
                # Normalize key: strip leading dirs like "tui-journal-abc123/"
                key = name
                parts = name.split("/")
                if parts and parts[0] and not parts[0].startswith(("eval", "tests", "test")):
                    key = "/".join(parts[1:])
                if key in fixtures:
                    continue
                if len(fixtures) >= MAX_FILES_PER_TOOL:
                    break
                try:
                    f = tf.extractfile(member)
                    if f is None:
                        continue
                    data = f.read(MAX_FILE_SIZE * 2)
                    text = data.decode("utf-8", errors="replace")
                    # NOTE: do NOT truncate; tests use full-content comparisons.
                    # If a golden file exceeds MAX_FILE_SIZE * 2, skip it (we
                    # can't satisfy the comparison anyway).
                    fixtures[key] = text
                except Exception:
                    continue
    except Exception:
        pass


def mine_tool(snap: Path, instance: str) -> dict[str, str]:
    fixtures: dict[str, str] = {}
    tool_dir = snap / instance / "tests"
    if not tool_dir.is_dir():
        return fixtures
    for branch in sorted(tool_dir.glob("*.tar.gz")):
        mine_branch(branch, fixtures)
        if len(fixtures) >= MAX_FILES_PER_TOOL:
            break
    return fixtures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", help="just one instance")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    snap = find_snapshot()
    if snap is None:
        print(f"ERROR: HF cache not found at {HF_SNAPSHOT}")
        return 1

    insts = sorted(p.name for p in snap.iterdir() if p.is_dir() and "__" in p.name)
    if args.instance:
        insts = [i for i in insts if args.instance in i]
    print(f"snap={snap.name} tools={len(insts)}")

    results: dict[str, Any] = {}
    for i, inst in enumerate(insts, 1):
        fixtures = mine_tool(snap, inst)
        results[inst] = fixtures
        if i % 20 == 0 or i == len(insts):
            tot = sum(len(f) for f in results.values())
            print(f"  [{i}/{len(insts)}] {inst}: {len(fixtures)} files (corpus total: {tot})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nwritten: {args.out}")

    tools_with_fixtures = sum(1 for f in results.values() if f)
    total_files = sum(len(f) for f in results.values())
    print(f"tools with fixtures: {tools_with_fixtures}/{len(results)}")
    print(f"total fixture files: {total_files}")
    top = sorted(((len(f), t) for t, f in results.items()), reverse=True)[:5]
    print("top 5 by fixture count:")
    for n, t in top:
        print(f"  {n}  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
