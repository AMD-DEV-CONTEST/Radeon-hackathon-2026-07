#!/usr/bin/env python3
"""classify_eval_failures.py - bucket failed test outcomes by *fixability*.

Distinguishes a REAL ceiling (byte-exact golden-file comparisons that no
generic scaffold can satisfy) from FIXABLE buckets (structural format checks,
specific flag handling, timeouts) so we never lazily dismiss a tool's score
as "ceiling" without proof.

Usage:
    python scripts/classify_eval_failures.py <path-to-eval.json>
    python scripts/classify_eval_failures.py --all     # all 8 chain tools
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Heuristic patterns matched against pytest's assertion failure output
# (the `output` field of each test_result entry).
# Order matters: first match wins.
PATTERNS = [
    # A — true ceiling: byte-exact comparison to a golden file or large literal
    ("A_golden_file", re.compile(r"\.golden|read_text\(\).*==|== .*read_text\(\)", re.IGNORECASE)),
    ("A_byte_exact", re.compile(r"assert.*\.stdout\s*==\s*[\"']", re.IGNORECASE)),
    # D — infrastructure / not a tool bug
    ("D_timeout", re.compile(r"TimeoutExpired|timeout(_method)?|Timeout|timed out", re.IGNORECASE)),
    (
        "D_subprocess",
        re.compile(r"CalledProcessError|subprocess\.|FileNotFoundError.*executable", re.IGNORECASE),
    ),
    # B — structural format check (FIXABLE in scaffold)
    ("B_substring", re.compile(r"assert.*\bin\b.*(?:stdout|stderr|output)", re.IGNORECASE)),
    ("B_line_count", re.compile(r"assert len\(.*lines.*\)\s*==", re.IGNORECASE)),
    ("B_column", re.compile(r"cols\[\d+\]|fields\[\d+\]|parts\[\d+\]", re.IGNORECASE)),
    ("B_returncode", re.compile(r"assert\s+result\.returncode\s*==\s*(\d+)", re.IGNORECASE)),
    ("B_regex_match", re.compile(r"re\.(search|match|findall|fullmatch)", re.IGNORECASE)),
    # C — specific flag / specific behavior
    ("C_specific_flag", re.compile(r"--[\w-]+", re.IGNORECASE)),
]

TIER_LABELS = {
    "A": "REAL CEILING (byte-exact, golden-file) - need per-tool hand-build",
    "B": "FIXABLE in scaffold (one patch lifts many tests)",
    "C": "FIXABLE per-flag (specific flag/behavior; bounded work)",
    "D": "INFRA (timeout/subprocess; not a tool-fit issue)",
    "E": "UNCLASSIFIED (look manually)",
}


def classify_failure(test_result: dict) -> str:
    """Return one of: A_*, B_*, C_*, D_*, E_unclassified.

    Pulls the assertion text out of `extra.message` and `extra.text` which
    is where ProgramBench actually stores the failure detail.
    """
    name = test_result.get("name") or ""
    extra = test_result.get("extra") or {}
    msg = extra.get("message") or ""
    text = extra.get("text") or ""
    # Also accept top-level output if present (older schema)
    output = test_result.get("output") or ""
    haystack = f"{name}\n{msg}\n{text[:2000]}\n{output[:1000]}"
    for label, regex in PATTERNS:
        if regex.search(haystack):
            return label
    return "E_unclassified"


def analyze(eval_json_path: Path) -> dict:
    with eval_json_path.open(encoding="utf-8") as f:
        data = json.load(f)
    results = data.get("test_results", []) or []
    if not results:
        return {"error": "no test_results"}

    passed = [r for r in results if r.get("status") == "passed"]
    # ProgramBench uses "failure" (not "failed"); also count "error" as fail.
    failed = [r for r in results if r.get("status") in ("failure", "failed", "error")]
    skipped = [r for r in results if r.get("status") == "skipped"]

    label_counts: Counter = Counter()
    for r in failed:
        label_counts[classify_failure(r)] += 1

    tier_counts: Counter = Counter()
    for label, n in label_counts.items():
        tier = label[0]  # A / B / C / D / E
        tier_counts[tier] += n

    total = len(results)
    npass = len(passed)
    base_pct = round(100.0 * npass / total, 2) if total else 0.0

    # Estimate "achievable ceiling" once Tier B + C + D issues are fixed
    fixable_failed = tier_counts.get("B", 0) + tier_counts.get("C", 0) + tier_counts.get("D", 0)
    achievable_max = npass + fixable_failed
    achievable_pct = round(100.0 * achievable_max / total, 2) if total else 0.0

    return {
        "path": str(eval_json_path),
        "tool": eval_json_path.stem.removesuffix(".eval"),
        "totals": {
            "tests": total,
            "passed": npass,
            "failed": len(failed),
            "skipped": len(skipped),
        },
        "current_score_pct": base_pct,
        "achievable_if_BCD_fixed_pct": achievable_pct,
        "ceiling_pct": round(100.0 * (npass + tier_counts.get("A", 0)) / total, 2)
        if total
        else 0.0,
        "tier_counts": dict(tier_counts),
        "label_counts": dict(label_counts.most_common()),
    }


def print_report(report: dict) -> None:
    print(f"=== {report['tool']} ===")
    t = report["totals"]
    print(
        f"  tests={t['tests']}  passed={t['passed']}  failed={t['failed']}  skipped={t['skipped']}"
    )
    print(f"  current score: {report['current_score_pct']}%")
    print(f"  ACHIEVABLE if BCD fixed: {report['achievable_if_BCD_fixed_pct']}%")
    print(f"  REAL ceiling (A only): {report['ceiling_pct']}%")
    print("  by tier:")
    for tier, n in sorted(report["tier_counts"].items()):
        label = TIER_LABELS.get(tier, "?")
        print(f"    {tier}: {n:>4}  {label}")
    print("  top labels:")
    for label, n in list(report["label_counts"].items())[:8]:
        print(f"    {label}: {n}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="eval.json paths")
    ap.add_argument(
        "--all", action="store_true", help="scan all factory dirs under T:/determinex-programbench"
    )
    args = ap.parse_args()

    paths: list[Path] = []
    if args.all:
        root = Path("T:/determinex-programbench")
        for d in sorted(root.glob("determinex_pb_factory_*_v1")):
            for ej in d.rglob("*.eval.json"):
                paths.append(ej)
    paths += [Path(p) for p in args.paths]

    if not paths:
        print("no eval.json paths provided")
        return 1

    summary: list[dict] = []
    for p in paths:
        if not p.is_file():
            print(f"skipping missing: {p}")
            continue
        rep = analyze(p)
        if "error" in rep:
            print(f"{p}: {rep['error']}")
            continue
        print_report(rep)
        summary.append(rep)

    if len(summary) > 1:
        print("=== ROLL-UP TABLE ===")
        print(f"  {'tool':<48} {'cur':>8} {'achievable':>12} {'realmax':>10}")
        for rep in sorted(summary, key=lambda r: -r["achievable_if_BCD_fixed_pct"]):
            print(
                f"  {rep['tool']:<48} {rep['current_score_pct']:>7.2f}% "
                f"{rep['achievable_if_BCD_fixed_pct']:>11.2f}% "
                f"{rep['ceiling_pct']:>9.2f}%"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
