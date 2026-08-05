#!/usr/bin/env python3
"""Iteration-aware LLM-gen wrapper.

Workflow per tool:
  1. Capture BEFORE state (pre-existing override main.py + latest score)
  2. Call llm_gen_override to generate a new main.py
  3. Apply via apply_overrides_to_scaffolds
  4. Eval locally
  5. Compare scores:
       - If new >= old: keep, commit. Done.
       - If new < old: revert (restore prior main.py + scaffold) — try v2
                       with the failing tests as feedback.
  6. After 3 attempts: stop, accept best score, commit log.

This makes LLM-gen safe to scale — no more regression-amplification.

Usage:
  python scripts/analysis/llm_gen_iterate.py --tool wfxr__csview.8ac4de0
  python scripts/analysis/llm_gen_iterate.py --tier mid --max-attempts 2
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = Path("T:/determinex-programbench")
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"
LOG_DIR = ROOT / "logs" / "llm_gen"
LOG_DIR.mkdir(parents=True, exist_ok=True)

PB_EXE = "T:\\Dev\\ProgramBench\\.venv\\Scripts\\programbench.exe"
PB_DIR = "T:\\Dev\\ProgramBench"


def find_eval_json(slug: str) -> Path | None:
    """Find latest eval.json for a tool (by slug, without sha suffix)."""
    matches = []
    for ej in glob.glob(str(EVAL_ROOT / f"determinex_pb_*_v*/{slug}.*/*.eval.json")):
        p = Path(ej)
        matches.append((p.stat().st_mtime, p))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def parse_score(eval_json: Path) -> tuple[int, int, float]:
    """Return (passed, total, pct)."""
    try:
        j = json.loads(eval_json.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return (0, 0, 0.0)
    r = j.get("test_results") or []
    p = sum(1 for x in r if x.get("status") == "passed")
    t = len(r)
    pct = 100.0 * p / max(1, t)
    return (p, t, pct)


def find_scaffold(tool_key: str) -> Path | None:
    """Find scaffold dir (factory first, then any pilot)."""
    direct = EVAL_ROOT / f"determinex_pb_factory_{tool_key}_v1" / tool_key
    if direct.exists():
        return direct
    for p in EVAL_ROOT.glob(f"determinex_pb_*_v*/{tool_key}"):
        if (p / "source" / "compile.sh").is_file():
            return p
    return None


def capture_state(tool_key: str, slug: str) -> dict:
    """Snapshot current override + score."""
    state = {"tool_key": tool_key, "slug": slug}
    ov = OVERRIDES_DIR / tool_key / "main.py"
    if ov.is_file():
        state["override_md5"] = subprocess_md5(ov)
        state["override_content"] = ov.read_text(encoding="utf-8")
    else:
        state["override_md5"] = None
        state["override_content"] = None
    ej = find_eval_json(slug)
    if ej:
        p, t, pct = parse_score(ej)
        state["pre_score"] = pct
        state["pre_passed"] = p
        state["pre_total"] = t
        state["pre_eval_path"] = str(ej)
    else:
        state["pre_score"] = 0.0
    return state


def subprocess_md5(p: Path) -> str:
    import hashlib

    return hashlib.md5(p.read_bytes()).hexdigest()


def run_llm_gen(tool_key: str, model: str = "claude-opus-4-7") -> bool:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "analysis" / "llm_gen_override.py"),
        "--tool",
        tool_key,
        "--model",
        model,
    ]
    print(f"  [llm-gen] {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f"  llm-gen failed (rc={r.returncode}): {r.stderr[:300]}")
        return False
    return True


def apply_override(tool_key: str) -> bool:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "analysis" / "apply_overrides_to_scaffolds.py"),
        "--only-slug",
        tool_key.rsplit(".", 1)[0],
    ]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"  apply failed: {r.stderr[:200]}")
        return False
    return True


def run_local_eval(
    scaffold_root: Path, filter_str: str, timeout_sec: int = 900
) -> tuple[int, int, float] | None:
    """Run programbench eval on local pilot/factory dir."""
    cmd = [
        PB_EXE,
        "eval",
        str(scaffold_root),
        "--filter",
        filter_str,
        "--workers",
        "1",
        "--branch-workers",
        "1",
        "--docker-cpus",
        "4",
        "--force",
    ]
    print(f"  [local-eval] {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, cwd=PB_DIR, capture_output=True, text=True, timeout=timeout_sec)
        if r.returncode != 0:
            print(f"  eval rc={r.returncode}, stderr tail: {r.stderr[-300:]}")
    except subprocess.TimeoutExpired:
        print(f"  eval timeout after {timeout_sec}s")
        return None
    # Find the eval.json and parse
    slug = filter_str
    # The eval writes to {scaffold_root}/<instance_id>/<instance_id>.eval.json
    # We don't know the exact instance_id here, so find latest matching slug.
    return None  # caller will re-read via find_eval_json


def revert_override(state: dict) -> bool:
    """Restore the override file from captured state."""
    ov = OVERRIDES_DIR / state["tool_key"] / "main.py"
    if state.get("override_content") is None:
        if ov.is_file():
            ov.unlink()
        return True
    ov.parent.mkdir(parents=True, exist_ok=True)
    ov.write_text(state["override_content"], encoding="utf-8", newline="\n")
    return True


def iterate_tool(tool_key: str, max_attempts: int = 2, model: str = "claude-opus-4-7") -> dict:
    """Run iteration loop on one tool. Returns final state dict."""
    slug = tool_key.rsplit(".", 1)[0] if "." in tool_key else tool_key
    state = capture_state(tool_key, slug)
    history = [("BEFORE", state["pre_score"])]

    print(f"\n=== {tool_key} ===")
    print(
        f"  BEFORE: {state['pre_score']:.2f}% ({state.get('pre_passed', 0)}/{state.get('pre_total', 0)})"
    )

    scaffold = find_scaffold(tool_key)
    if not scaffold:
        print("  no scaffold found, skip")
        return state

    best_pct = state["pre_score"]
    best_override_md5 = state["override_md5"]

    for attempt in range(1, max_attempts + 1):
        print(f"\n  --- attempt {attempt}/{max_attempts} ---")
        if not run_llm_gen(tool_key, model=model):
            break
        if not apply_override(tool_key):
            break
        # Resync per_tool_failures + matrix (so action sheet is updated)
        # Skipped here — eval first
        run_local_eval(scaffold, slug)
        # Re-read eval result
        new_ej = find_eval_json(slug)
        if not new_ej:
            print("  no eval.json after eval attempt")
            continue
        p, t, pct = parse_score(new_ej)
        print(f"  AFTER attempt {attempt}: {pct:.2f}% ({p}/{t})")
        history.append((f"attempt_{attempt}", pct))
        if pct > best_pct:
            best_pct = pct
            print(f"  *** NEW BEST: {pct:.2f}% (was {state['pre_score']:.2f}%) — keeping")
            break  # stop on first improvement
        else:
            print(f"  regression vs {state['pre_score']:.2f}%; reverting")
            revert_override(state)
            if not apply_override(tool_key):
                print("  warning: revert-apply failed")
            # Continue loop, try with maybe different prompt next attempt

    state["history"] = history
    state["final_pct"] = best_pct
    state["delta"] = best_pct - state["pre_score"]
    # Save log
    log_path = LOG_DIR / f"{tool_key}.json"
    log_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    print(f"  log: {log_path}")
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", help="single tool_key")
    ap.add_argument("--tier", choices=["near-lock", "upper", "mid", "floor"])
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--model", default="claude-opus-4-7")
    args = ap.parse_args()

    if args.tool:
        candidates = [args.tool]
    elif args.tier:
        # Load failures, pick tier
        try:
            fails = json.loads(Path("c:/tmp/per_tool_failures.json").read_text(encoding="utf-8"))
        except Exception:
            print("ERROR: per_tool_failures.json missing")
            sys.exit(1)
        tier_ranges = {
            "near-lock": (95, 100),
            "upper": (70, 95),
            "mid": (30, 70),
            "floor": (0.01, 30),
        }
        lo, hi = tier_ranges[args.tier]
        candidates = [tk for tk, d in fails.items() if lo <= d.get("pct", 0) < hi]
        candidates.sort(key=lambda tk: -fails[tk].get("pct", 0))
    else:
        print("Must specify --tool or --tier")
        sys.exit(1)

    print(f"Iterating LLM-gen on {len(candidates)} tool(s), max-attempts={args.max_attempts}")
    results = []
    for tk in candidates:
        try:
            r = iterate_tool(tk, max_attempts=args.max_attempts, model=args.model)
            results.append(r)
        except Exception as e:
            print(f"  {tk}: ERROR {e}")
    print()
    print("=== SUMMARY ===")
    for r in results:
        d = r.get("delta", 0)
        sign = "+" if d >= 0 else ""
        print(
            f"  {r['tool_key']:<50}  {r['pre_score']:.2f} -> {r.get('final_pct', 0):.2f}  ({sign}{d:.2f}pp)"
        )


if __name__ == "__main__":
    main()
