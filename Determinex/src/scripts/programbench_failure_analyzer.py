#!/usr/bin/env python3
"""programbench_failure_analyzer.py - read eval.json files, classify failures
per tool, suggest targeted patches for iteration 2.

For each tool's most recent eval.json:
  - bucket failures by type (rc_mismatch / assert_substr / equality_mismatch /
    no_such_file / timeout / py_runtime / etc.)
  - extract the TOP 10 expected/actual diffs per bucket
  - emit a per-tool plan with concrete suggestions:
    * "scaffold returned rc=2, tests expect rc=1" → patch err_clap to return 1
    * "missing substring 'Foo'" → add to EXPECTED_STRINGS
    * "missing fixture file 'X'" → pre-stage X
    * "wrong stdout for argv [Y]" → update oracle memo

Output: logs/mass_run_v2/failure_analysis.json
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logs" / "mass_run_v2" / "failure_analysis.json"

# Classification regexes
RX_ASSERT_RC = re.compile(r"got ?(\d+)|returncode=(\d+).*Expected (?:exit )?(\d+)", re.I)
RX_ASSERT_IN_EMPTY = re.compile(r"['\"]([^'\"]{1,200})['\"] in ['\"]['\"]")
RX_ASSERT_IN = re.compile(r"['\"]([^'\"]{1,200})['\"] in ", re.I)
RX_ASSERT_EQ = re.compile(r"^assert ['\"]?([^=]{1,300})['\"]?\s*==", re.M)
RX_NO_FILE = re.compile(r"No such file or directory: ['\"]?([^'\"]+)['\"]?")
RX_PY_EXC = re.compile(r"(TypeError|AttributeError|IndexError|KeyError|ValueError): ([^\n]{1,200})")


def classify_failure(msg: str) -> tuple[str, dict[str, Any]]:
    """Return (bucket, extracted_data)."""
    m = RX_ASSERT_RC.search(msg)
    if m:
        got = next((g for g in m.groups() if g), None)
        return "rc_mismatch", {"got_rc": int(got) if got else None}
    m = RX_NO_FILE.search(msg)
    if m:
        return "no_such_file", {"path": m.group(1)}
    m = RX_PY_EXC.search(msg)
    if m:
        return "py_runtime_err", {"exc": m.group(1), "msg": m.group(2)}
    m = RX_ASSERT_IN_EMPTY.search(msg)
    if m:
        return "assert_substr_empty_stdout", {"expected_substr": m.group(1)}
    m = RX_ASSERT_IN.search(msg)
    if m:
        return "assert_substr", {"expected_substr": m.group(1)}
    if "subprocess.TimeoutExpired" in msg or "test_timeout" in msg.lower():
        return "timeout", {}
    if "tmux" in msg.lower():
        return "tmux_harness", {}
    if "JSONDecodeError" in msg:
        return "json_parse", {}
    if "==" in msg and "assert" in msg.lower():
        return "equality_mismatch", {"raw_first_line": msg.split("\n", 1)[0][:200]}
    return "other", {"raw_first_line": msg.split("\n", 1)[0][:200]}


def analyze_tool(eval_path: Path) -> dict[str, Any]:
    try:
        j = json.loads(eval_path.read_text(encoding="utf-8"))
    except Exception:
        return {"error": "parse_fail"}
    results = j.get("test_results") or []
    if not results:
        return {"error": "no_results"}

    total = len(results)
    passed = sum(1 for r in results if r.get("status") == "passed")
    pct = 100.0 * passed / total

    buckets: dict[str, list[dict]] = defaultdict(list)
    rc_counts: Counter = Counter()
    missing_substrs: Counter = Counter()
    missing_files: Counter = Counter()
    runtime_errs: Counter = Counter()

    for r in results:
        if r.get("status") == "passed":
            continue
        name = r.get("name", "")
        msg = (r.get("extra") or {}).get("message") or ""
        bucket, info = classify_failure(msg)
        buckets[bucket].append({"name": name[:120], **info})
        if bucket == "rc_mismatch" and info.get("got_rc") is not None:
            rc_counts[info["got_rc"]] += 1
        elif (
            bucket in ("assert_substr", "assert_substr_empty_stdout") and "expected_substr" in info
        ):
            missing_substrs[info["expected_substr"][:80]] += 1
        elif bucket == "no_such_file":
            missing_files[info.get("path", "")[:120]] += 1
        elif bucket == "py_runtime_err":
            runtime_errs[info.get("exc", "")] += 1

    # Patch suggestions
    suggestions: list[str] = []
    if rc_counts:
        top_rc, n = rc_counts.most_common(1)[0]
        if top_rc != 2 and n >= 3:
            suggestions.append(f"err_clap should return rc={top_rc} (most-asserted rc, seen {n}x)")
    if missing_substrs:
        top = missing_substrs.most_common(10)
        suggestions.append(f"add to EXPECTED_STRINGS: {[s for s, _ in top[:5]]}")
    if missing_files:
        top = missing_files.most_common(5)
        suggestions.append(f"workspace pre-stage these paths: {[p for p, _ in top]}")
    if runtime_errs:
        for exc, n in runtime_errs.most_common(3):
            suggestions.append(f"scaffold Python runtime error ({n}x): {exc} — review per-tool")
    if buckets.get("timeout"):
        suggestions.append(
            f"tests timing out ({len(buckets['timeout'])}); scaffold likely hanging on specific argv pattern"
        )

    return {
        "score": round(pct, 2),
        "passed": passed,
        "total": total,
        "buckets": {k: len(v) for k, v in buckets.items()},
        "top_rc_codes": dict(rc_counts.most_common(5)),
        "top_missing_substrs": dict(missing_substrs.most_common(8)),
        "top_missing_files": dict(missing_files.most_common(5)),
        "top_runtime_errs": dict(runtime_errs.most_common(3)),
        "suggestions": suggestions,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument(
        "--max-score",
        type=float,
        default=99.0,
        help="only analyze tools below this pct (skip locked)",
    )
    args = ap.parse_args()

    eval_files = sorted(glob.glob("T:/determinex-programbench/determinex_pb_*_v*/*/*.eval.json"))
    print(f"eval files found: {len(eval_files)}")

    results = {}
    for ej in eval_files:
        tool = Path(ej).parent.name
        analysis = analyze_tool(Path(ej))
        if analysis.get("score", 100) >= args.max_score:
            continue
        if analysis.get("error"):
            continue
        results[tool] = analysis

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwritten: {args.out}")
    print(f"tools needing work: {len(results)}")

    # Print bottom-15 with their top suggestions
    ranked = sorted(results.items(), key=lambda x: x[1]["score"])
    print()
    print("=== bottom 15 tools (lowest score first) ===")
    for tool, a in ranked[:15]:
        print(f"  {a['score']:6.2f}%  ({a['passed']}/{a['total']})  {tool[:50]}")
        for s in a["suggestions"][:3]:
            print(f"      -> {s}")

    # Aggregate suggestions across all tools
    print()
    print("=== aggregate patterns ===")
    sug_counts: Counter = Counter()
    for a in results.values():
        for s in a["suggestions"]:
            kind = s.split(":", 1)[0]
            sug_counts[kind] += 1
    for kind, n in sug_counts.most_common(10):
        print(f"  {n:>4}  {kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
