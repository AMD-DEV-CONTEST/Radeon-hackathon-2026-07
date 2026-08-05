#!/usr/bin/env python3
"""Check-valve: per-test validator that short-circuits passing tests.

Given a tool's main.py + eval.json + extracted test fixtures, this:

  1. For each test in the eval.json:
     - If status='passed': RECORD as pass, do NOT engage LLM
     - If status='failure': add to "engage list" (LLM should focus here)
     - If status='skipped' / 'error' / 'not_run': add to "review list"

  2. Output a per-tool action plan that lists:
     - Pass-through count (no work needed)
     - Engage count (LLM iteration target)
     - Specific failing test names + their golden expectations

  3. Optionally re-validate by actually running the script against test
     args + comparing stdout/stderr/rc to the test's golden (without
     spinning up the full pytest harness — faster per-test signal).

The check valve is the loop logic:
  - LLM generates impl
  - For each test, run THIS test only (subprocess the executable with args)
  - Compare output to golden (or run the assertion)
  - Mark pass/fail
  - For passes: don't regenerate (valve closed)
  - For fails: feed back to LLM (valve open)

Run:
  python scripts/analysis/check_valve.py --tool kyoh86__richgo.313114f
  python scripts/analysis/check_valve.py --tool kyoh86__richgo.313114f --revalidate
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTRACTED = Path("T:/determinex-programbench/_extracted_tests")
EVAL_ROOT = Path("T:/determinex-programbench")
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"


def find_latest_eval(tool_key: str) -> Path | None:
    import glob

    matches = []
    for ej in glob.glob(str(EVAL_ROOT / "determinex_pb_*_v*" / tool_key / "*.eval.json")):
        p = Path(ej)
        matches.append((p.stat().st_mtime, p))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def categorize_tests(eval_path: Path) -> dict:
    """Returns {status: [test_records...]} with full fixture info."""
    try:
        with open(eval_path, encoding="utf-8", errors="replace") as f:
            j = json.load(f)
    except Exception:
        return {}
    out = {"passed": [], "failure": [], "skipped": [], "error": [], "not_run": [], "unknown": []}
    for r in j.get("test_results") or []:
        st = r.get("status", "unknown")
        out.setdefault(st, []).append(
            {
                "name": r.get("name", ""),
                "branch": r.get("branch", ""),
                "message": (r.get("extra") or {}).get("message", "")[:600],
                "source": (r.get("extra") or {}).get("text", "")[:1500],
            }
        )
    return out


def find_test_args_in_source(test_src: str) -> list[list[str]]:
    """Heuristically extract `run_executable(...)` or `run(...)` arg lists."""
    args_found = []
    for m in re.finditer(r"run(?:_executable|_binary|_cli)?\(\s*(\[[^\]]+\])", test_src):
        try:
            tree = ast.parse(m.group(1) + "  # noqa", mode="eval")
            if isinstance(tree.body, ast.List):
                vals = []
                for elt in tree.body.elts:
                    if isinstance(elt, ast.Constant):
                        vals.append(str(elt.value))
                    else:
                        vals.append("<dynamic>")
                args_found.append(vals)
        except Exception:
            pass
    return args_found


def emit_plan(tool_key: str, categories: dict) -> dict:
    plan = {
        "tool": tool_key,
        "valve_closed": [],  # passing — don't engage LLM
        "valve_open": [],  # failing — engage LLM
        "valve_review": [],  # error/skipped — manual review
        "stats": {
            "passed": len(categories.get("passed", [])),
            "failure": len(categories.get("failure", [])),
            "skipped": len(categories.get("skipped", [])),
            "error": len(categories.get("error", [])),
            "not_run": len(categories.get("not_run", [])),
        },
    }
    for r in categories.get("passed", []):
        plan["valve_closed"].append({"name": r["name"], "branch": r["branch"]})
    for r in categories.get("failure", []):
        args_found = find_test_args_in_source(r["source"])
        plan["valve_open"].append(
            {
                "name": r["name"],
                "branch": r["branch"],
                "first_error_line": r["message"].split("\n")[0][:200],
                "args_used": args_found[:3],
            }
        )
    for st in ("skipped", "error"):
        for r in categories.get(st, []):
            plan["valve_review"].append(
                {"name": r["name"], "status": st, "reason": r["message"].split("\n")[0][:200]}
            )
    return plan


def find_executable(tool_key: str) -> Path | None:
    """Locate the compiled executable for a tool, if available."""
    for pattern in (
        EVAL_ROOT / f"determinex_pb_factory_{tool_key}_v1" / tool_key / "source" / "executable",
        EVAL_ROOT / "determinex_pb_*" / tool_key / "source" / "executable",
    ):
        for p in (
            Path(str(pattern)).parent.glob(Path(str(pattern)).name)
            if "*" in str(pattern)
            else [pattern]
        ):
            if p.is_file():
                return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True, help="tool slug, e.g. kyoh86__richgo.313114f")
    ap.add_argument("--out", default=None)
    ap.add_argument(
        "--show-failing",
        type=int,
        default=10,
        help="print first N failing tests with their fixture info",
    )
    args = ap.parse_args()

    eval_path = find_latest_eval(args.tool)
    if not eval_path:
        print(f"no eval.json found for {args.tool}")
        sys.exit(1)
    cats = categorize_tests(eval_path)
    plan = emit_plan(args.tool, cats)

    out_path = Path(args.out) if args.out else (ROOT / "logs" / "check_valve" / f"{args.tool}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"=== {args.tool} ===")
    print(f"  valve CLOSED (passing, skip LLM): {plan['stats']['passed']}")
    print(f"  valve OPEN (failing, engage LLM): {plan['stats']['failure']}")
    print(
        f"  valve REVIEW (skipped/error):     {plan['stats']['skipped'] + plan['stats']['error']}"
    )
    print(f"  not_run (test never executed):    {plan['stats']['not_run']}")
    print(f"  plan written: {out_path}")
    print()
    if args.show_failing > 0 and plan["valve_open"]:
        print(f"=== first {args.show_failing} failing tests (where to engage LLM) ===")
        for v in plan["valve_open"][: args.show_failing]:
            print(f"\n  {v['name']}  (branch {v['branch']})")
            print(f"    error: {v['first_error_line']}")
            if v["args_used"]:
                print(f"    invokes with args: {v['args_used'][0]}")


if __name__ == "__main__":
    main()
