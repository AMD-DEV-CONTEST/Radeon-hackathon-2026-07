#!/usr/bin/env python3
"""PB Action Sheets — per-tool action sheets that show the EXACT failing
test names + assertion messages + golden vs actual output so we can patch
surgically without re-digging through eval.jsons each time.

For each evaluated tool, writes:
  corpus/programbench/results/action_sheets/<tool>.md

Each sheet contains:
  - Header: current %, pass/fail/skip, frontier %
  - Skipped section (with reasons)
  - Per-bucket failures: bucket name + count + 3 sample tests with messages
  - "Quick patch ideas" section computed from bucket signatures

Usage: python scripts/analysis/pb_action_sheets.py
       python scripts/analysis/pb_action_sheets.py --only ripgrep,htmlq
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import re
from pathlib import Path

ROOT = Path("T:/determinex-programbench")
# Derived from this file's location; the absolute form ran on exactly one machine.
_REPO = Path(__file__).resolve().parents[2]
OUT_DIR = _REPO / "corpus" / "programbench" / "results" / "action_sheets"


def root_cause_bucket(first_line: str) -> str:
    fl = first_line.lower()
    if "assertionerror" in fl or "assert " in fl:
        m = re.search(r"assert\s+(\d+)\s*==\s*(\d+)", fl)
        if m:
            return f"rc_mismatch_got{m.group(1)}_want{m.group(2)}"
        if re.search(r"assert\s+\d+\s*!=\s*\d+", fl):
            return "rc_unexpected_zero"
        if "assert false" in fl:
            return "boolean_false"
        if "assert none" in fl:
            return "returned_none"
        if "==" in fl and "b'" in fl:
            return "bytes_output_mismatch"
        if "==" in fl and "'" in fl:
            return "string_output_mismatch"
        return "other_assertion"
    if "jsondecodeerror" in fl:
        return "json_output_missing_or_bad"
    if "brokenpipeerror" in fl:
        return "sigpipe_unhandled"
    if "indexerror" in fl:
        return "empty_list_or_string"
    if "keyerror" in fl:
        return "missing_dict_key"
    if "typeerror" in fl:
        return "type_error"
    if "filenotfounderror" in fl:
        return "missing_file"
    if "calledprocesserror" in fl:
        return "subprocess_failed"
    if "timeout" in fl:
        return "test_timeout"
    return "uncategorized"


def patch_ideas_for_bucket(bucket: str) -> list[str]:
    ideas = {
        "rc_mismatch_got0_want1": [
            "Check argv: if invalid input → `sys.exit(1)`",
            "Wrap main body in try/except → exit(1) on parse error",
        ],
        "rc_mismatch_got0_want2": [
            "No args → print usage to stderr + `sys.exit(2)` (POSIX usage convention)",
            "Unknown flag → `sys.exit(2)`",
        ],
        "rc_mismatch_got1_want0": [
            "Tool is over-erroring on valid input; relax error condition",
            "Specifically check what input triggers rc=1 in golden",
        ],
        "rc_mismatch_got2_want0": [
            "Tool exits with usage error on valid args; check argv parsing",
            "Missing required flag detection too aggressive",
        ],
        "rc_unexpected_zero": [
            "Tool returns success on invalid input; add validation",
        ],
        "string_output_mismatch": [
            "Compare actual vs golden output for one failing test, identify format diff",
            "Common: trailing newline, ANSI color codes, locale formatting",
        ],
        "bytes_output_mismatch": [
            "Likely ANSI color, terminal escape sequences, or binary framing",
            "Match exact byte sequence from golden",
        ],
        "json_output_missing_or_bad": [
            "Add `--format json` flag; emit `json.dumps()` of result dict",
        ],
        "sigpipe_unhandled": [
            "Top of main.py: `import signal; signal.signal(signal.SIGPIPE, signal.SIG_DFL)`",
        ],
        "boolean_false": [
            "Generic boolean check; inspect specific test to find what's expected False",
        ],
        "returned_none": [
            "Function returning None unexpectedly; check return statements",
        ],
        "empty_list_or_string": [
            "Defensive: check list/string emptiness before indexing",
        ],
        "missing_file": [
            "Scaffold not creating expected output file; check write logic",
        ],
        "type_error": [
            "Specific TypeError; check arg types vs expected",
        ],
    }
    return ideas.get(bucket, ["Inspect samples manually"])


def write_sheet(tool: str, eval_path: Path, only_failed_top_n: int = 5):
    try:
        j = json.loads(eval_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! skip {tool}: parse error {e}")
        return False
    results = j.get("test_results") or []
    statuses = collections.Counter(r.get("status") for r in results)
    passed = statuses.get("passed", 0)
    failed = [r for r in results if r.get("status") == "failure"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    total = len(results)
    if total == 0:
        return False

    # Group failures by bucket
    by_bucket = collections.defaultdict(list)
    for r in failed:
        msg = (r.get("extra") or {}).get("message") or ""
        fl = msg.strip().split("\n")[0][:200]
        bucket = root_cause_bucket(fl)
        by_bucket[bucket].append({"name": r.get("name", ""), "message": msg, "first": fl})

    sorted_buckets = sorted(by_bucket.items(), key=lambda kv: -len(kv[1]))

    pct = round(100.0 * passed / total, 2)

    out = []
    out.append(f"# Action Sheet — {tool}")
    out.append("")
    out.append(f"**Current:** {pct}%  ({passed}/{total})")
    out.append(f"**Pass / Fail / Skip:** {passed} / {len(failed)} / {len(skipped)}")
    out.append(f"**Gap to 100%:** {100 - pct:.2f} percentage points ({total - passed} tests)")
    out.append("")

    if skipped:
        out.append("## Skipped tests")
        out.append("")
        out.append(
            "PB counts skipped as non-passing for Resolved metric. Triage these first if no real failures."
        )
        out.append("")
        for r in skipped[:5]:
            reason = (r.get("extra") or {}).get("message") or "<no-reason>"
            reason_first = reason.strip().split("\n")[0][:200]
            out.append(f"- `{r.get('name', '')}`")
            out.append(f"  - reason: {reason_first}")
        if len(skipped) > 5:
            out.append(f"- *(... {len(skipped) - 5} more skipped)*")
        out.append("")

    if not failed:
        out.append("## No actual failures")
        out.append("")
        out.append(
            "All non-passing tests are skipped. Address skipped reasons above to reach 100%."
        )
    else:
        out.append("## Failure clusters")
        out.append("")
        out.append(
            f"{len(failed)} failed tests grouped into {len(by_bucket)} buckets (sorted by count)."
        )
        out.append("")

        for bucket, items in sorted_buckets:
            out.append(f"### `{bucket}` — {len(items)} test(s)")
            out.append("")
            out.append("**Quick patch ideas:**")
            for idea in patch_ideas_for_bucket(bucket):
                out.append(f"- {idea}")
            out.append("")
            out.append("**Sample failures:**")
            out.append("")
            for r in items[:3]:
                out.append(f"- `{r['name']}`")
                # Indent the message
                msg_lines = r["message"].split("\n")[:8]
                for ml in msg_lines:
                    out.append(f"  > {ml[:200]}")
            if len(items) > 3:
                out.append(f"- *(... {len(items) - 3} more in this cluster)*")
            out.append("")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet_path = OUT_DIR / f"{tool}.md"
    sheet_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated tool slug filter (substring match)")
    ap.add_argument("--limit", type=int, default=0, help="cap number of sheets generated")
    args = ap.parse_args()
    only = [s.strip().lower() for s in args.only.split(",") if s.strip()]

    latest = {}
    for p in glob.glob(str(ROOT / "determinex_pb_*_v*" / "*" / "*.eval.json")):
        pp = Path(p)
        tool = pp.parent.name
        mt = pp.stat().st_mtime
        if tool not in latest or mt > latest[tool][0]:
            latest[tool] = (mt, pp)

    count = 0
    for tool, (_, ej) in sorted(latest.items()):
        if only and not any(s in tool.lower() for s in only):
            continue
        if args.limit and count >= args.limit:
            break
        ok = write_sheet(tool, ej)
        if ok:
            count += 1
    print(f"wrote {count} action sheets to {OUT_DIR}")


if __name__ == "__main__":
    main()
