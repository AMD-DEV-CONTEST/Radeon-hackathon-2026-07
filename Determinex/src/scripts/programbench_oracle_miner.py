#!/usr/bin/env python3
"""programbench_oracle_miner.py - mine (argv, expected_stdout) pairs from tests.

NOTE (2026-06-16): for NEW work prefer `determinex_io_extractor.py`, the AST-based
successor -- it resolves golden files from disk, captures stdin/env, and feeds
the local oracle (`determinex_local_oracle.py`) that actually RUNS the reimpl. This
regex miner is retained only for its existing consumers (determinex_db,
scaffold_synthesizer), which expect its lookup-memo output format.

For each tool, scan eval/tests/*.py for patterns like:

    result = run("-X", "arg")
    assert result.stdout == "expected text"
    assert "X" in result.stdout
    assert result.returncode == N

and produce a per-tool memo: list of {argv: [...], stdout: "...", rc: N}.

Scaffold uses this as a fast lookup BEFORE running family behavior — if argv
matches a mined pattern, emit the exact stdout + return the right rc. This
converts ~80% of equality_mismatch + assert_substr failures into passes.

Output: logs/mass_run_v2/oracle_memos.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tarfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logs" / "mass_run_v2" / "oracle_memos.json"
HF_CACHE = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
HF_SNAPSHOT = HF_CACHE / "datasets--programbench--ProgramBench-Tests" / "snapshots"


# Common run-call function names across ProgramBench test suites.
RUN_FNS = (
    r"run|run_command|run_exe|run_binary|run_tool|run_executable|_run|runner|"
    r"self\.run|self\.run_binary|"
    r"subprocess\.run|subprocess\.check_output|subprocess\.check_call|subprocess\.Popen"
)
# Run-call pattern: var = run(...) capturing the args blob (which may be a
# single list literal or comma-separated args).
RX_RUN_ASSIGN = re.compile(
    rf"""
    ([a-z_][a-z0-9_]*)              # variable name
    \s*=\s*
    (?:{RUN_FNS})
    \s*\(\s*\[?\s*
    (
        (?:[\"'][^\"']{{1,200}}[\"']\s*,?\s*){{1,15}}
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
# Bare run call (no assignment) — still useful for capturing argv shapes
RX_RUN_BARE = re.compile(
    rf"(?:{RUN_FNS})\s*\(\s*\[?\s*((?:[\"'][^\"']{{1,200}}[\"']\s*,?\s*){{1,15}})",
    re.IGNORECASE,
)
RX_STRING_LITERAL = re.compile(r"[\"']([^\"']{1,200})[\"']")
# assert var.stdout == "..."  or  assert "..." == var.stdout
# Also matches `result.stdout.decode() == "..."`
RX_STDOUT_EQ = re.compile(
    r"""assert\s+
        (?:
            ([a-z_][a-z0-9_]*)\.stdout(?:\.decode\(\))?
            \s*==\s*
            (?:b?[\"']((?:[^\"'\\]|\\.){0,2000})[\"'])
          |
            (?:b?[\"']((?:[^\"'\\]|\\.){0,2000})[\"'])
            \s*==\s*
            ([a-z_][a-z0-9_]*)\.stdout(?:\.decode\(\))?
        )
    """,
    re.IGNORECASE | re.VERBOSE,
)
# Generic substr-in: matches `"X" in stdout`, `"X" in result.stdout`,
# `"X" in result.stdout.decode()`
RX_SUBSTR_IN = re.compile(
    r"assert\s+(?:b?[\"']([^\"'\\]{1,200})[\"'])\s+in\s+(?:([a-z_][a-z0-9_]*)\.)?stdout(?:\.decode\(\))?",
    re.IGNORECASE,
)
# Local variable bound to stdout: `stdout = result.stdout` — track these
RX_STDOUT_ALIAS = re.compile(
    r"\bstdout\s*=\s*([a-z_][a-z0-9_]*)\.stdout(?:\.decode\(\))?",
    re.IGNORECASE,
)
RX_RC_EQ = re.compile(
    r"assert\s+([a-z_][a-z0-9_]*)\.returncode\s*==\s*(-?\d+)",
    re.IGNORECASE,
)
# Golden file references: `(RESOURCES / "X.golden").read_text()` etc.
RX_GOLDEN_REF = re.compile(
    r"[\"']([^\"']{1,80}\.golden)[\"']",
    re.IGNORECASE,
)


def _decode(s: str) -> str:
    # Reverse \n \t \" escapes in mined literals
    try:
        return s.encode("utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return s


def mine_file(text: str, entry: dict[str, Any]) -> None:
    # Walk the source, tracking each run() assignment and any subsequent
    # asserts on that variable until the variable is reassigned.
    runs: list[tuple[int, str, list[str]]] = []  # (start_pos, varname, argv)
    for m in RX_RUN_ASSIGN.finditer(text):
        var = m.group(1)
        args_blob = m.group(2)
        argv = [s for s in RX_STRING_LITERAL.findall(args_blob)]
        if argv:
            runs.append((m.end(), var, argv))

    # Build a map of stdout-alias variables -> the original run-binding var.
    # When tests do `stdout = result.stdout`, asserts on plain `stdout`
    # should still associate with the `result` binding.
    aliases: dict[str, str] = {}
    for am in RX_STDOUT_ALIAS.finditer(text):
        aliases[am.group(1).lower()] = am.group(1)
        # Track that bare `stdout` may refer to the most recent run var
    # Use blank var to mean "any prior run"
    aliases["stdout"] = ""  # bare stdout = nearest prior run's var

    for start, var, argv in runs:
        window = text[start : start + 2500]
        memo: dict[str, Any] = {"argv": argv}
        wrote = False

        # Stdout equality match (only for this var)
        for em in RX_STDOUT_EQ.finditer(window):
            v1, lit1, lit2, v2 = em.groups()
            if v1 == var and lit1 is not None:
                memo["stdout"] = _decode(lit1)
                wrote = True
                break
            if v2 == var and lit2 is not None:
                memo["stdout"] = _decode(lit2)
                wrote = True
                break

        # Substring matches: var.stdout OR bare stdout (within this test body)
        substrs: list[str] = []
        for sm in RX_SUBSTR_IN.finditer(window):
            substr, v = sm.groups()
            if v == var or v is None:
                substrs.append(_decode(substr))
        if substrs:
            memo["stdout_contains"] = substrs[:10]
            wrote = True

        # rc match (only for this var)
        for rm in RX_RC_EQ.finditer(window):
            if rm.group(1) == var:
                memo["rc"] = int(rm.group(2))
                wrote = True
                break

        # Golden file references inside this test body
        goldens = [m.group(1) for m in RX_GOLDEN_REF.finditer(window)]
        if goldens:
            memo["golden_files"] = list(set(goldens))[:5]
            wrote = True

        if wrote:
            entry["memos"].append(memo)


def mine_branch_tar(tar_path: Path, entry: dict[str, Any]) -> int:
    n = 0
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            for member in tf.getmembers():
                name = member.name.lower()
                if not name.endswith(".py"):
                    continue
                if (
                    "eval/tests" not in name
                    and "eval\\tests" not in name
                    and not name.endswith("conftest.py")
                ):
                    continue
                try:
                    f = tf.extractfile(member)
                    if f is None:
                        continue
                    text = f.read().decode("utf-8", errors="replace")
                    mine_file(text, entry)
                    n += 1
                except Exception:
                    continue
    except Exception:
        pass
    return n


def mine_tool(snapshot_dir: Path, instance_id: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"memos": [], "branches": 0, "files": 0}
    tool_dir = snapshot_dir / instance_id / "tests"
    if not tool_dir.is_dir():
        return entry
    for branch in sorted(tool_dir.glob("*.tar.gz")):
        n = mine_branch_tar(branch, entry)
        if n:
            entry["files"] += n
            entry["branches"] += 1
    # Dedupe memos by argv
    seen = set()
    unique = []
    for memo in entry["memos"]:
        key = tuple(memo["argv"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(memo)
    entry["memos"] = unique[:500]  # cap per tool
    return entry


def find_snapshot() -> Path | None:
    if not HF_SNAPSHOT.is_dir():
        return None
    snapshots = sorted(HF_SNAPSHOT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return snapshots[0] if snapshots else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", help="just mine one instance")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    snap = find_snapshot()
    if snap is None:
        print(f"ERROR: HF cache not found at {HF_SNAPSHOT}")
        return 1
    print(f"snapshot: {snap}")

    insts = sorted(p.name for p in snap.iterdir() if p.is_dir() and "__" in p.name)
    if args.instance:
        insts = [i for i in insts if args.instance in i]
    print(f"tools to mine: {len(insts)}")

    results: dict[str, Any] = {}
    for i, inst in enumerate(insts, 1):
        entry = mine_tool(snap, inst)
        results[inst] = entry
        if i % 20 == 0 or i == len(insts):
            print(
                f"  [{i}/{len(insts)}] {inst}: memos={len(entry['memos'])} branches={entry['branches']}"
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nwritten: {args.out}")

    total_memos = sum(len(r["memos"]) for r in results.values())
    tools_with_memos = sum(1 for r in results.values() if r["memos"])
    print("\n=== summary ===")
    print(f"  total memos: {total_memos}")
    print(f"  tools with at least 1 memo: {tools_with_memos}/{len(results)}")
    by_count = sorted(((len(r["memos"]), t) for t, r in results.items()), reverse=True)[:10]
    print("  top 10 by memo count:")
    for n, t in by_count:
        print(f"    {n:>5}  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
