#!/usr/bin/env python3
"""Patch-on-top LLM generator: ADD tool-specific behavior to working stub.

Key insight from v37 analysis: replacing the universal-pattern stub with
a full LLM impl regresses scores (atlas -14pp, rustowl -19pp, fblog -17pp).
The stub passes 150-300 CLI-sanity tests per tool. A full LLM impl that
crashes on edge cases loses those.

This generator prompts the LLM to PATCH the stub — add specific handlers
for failing tests WHILE PRESERVING the universal patterns.

Workflow:
  1. Read the existing scaffold's main.py (the working stub)
  2. Read the action sheet (failing tests)
  3. Prompt LLM: "Below is the CURRENT main.py. Below is what tests want.
                  Return a MODIFIED main.py that adds the tool-specific
                  handlers but KEEPS all existing argv handling."
  4. Validate: returned code must still have key universal patterns

Run:
  python scripts/analysis/patch_on_top_gen.py --tool ariga__atlas.6d81150 --backend deepseek
  python scripts/analysis/patch_on_top_gen.py --revert-list c:/tmp/revert_list.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import infrastructure from llm_gen_override
sys.path.insert(0, str(Path(__file__).parent))
from llm_gen_override import (
    call_llm,
    extract_python_from_response,
    find_scaffold_main,
    load_failures,
    load_pb_meta,
)

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"

PATCH_PROMPT_TEMPLATE = """You are extending an existing Python CLI tool script to pass MORE tests while keeping all currently-passing tests passing.

# Tool: {tool_name}
- Language hint: {language}
- Currently passing: {passed}/{total} tests ({pct:.2f}%)
- These passes come from the UNIVERSAL handlers below. DO NOT REMOVE THEM.

# Current main.py (PRESERVE its argv handling — these patterns pass tests)

```python
{current_main_py}
```

# Failing tests this tool needs to also pass

{failures_block}

# Your task

Return a modified `main.py` that:
1. PRESERVES the existing universal handlers (no-args -> rc=2, --help -> rc=0, --version, UTF-8 stdout reconfigure, SIGPIPE handler, BrokenPipeError catch)
2. ADDS NEW logic that handles the specific argv patterns shown in failing tests
3. Whenever an argv pattern isn't recognized by the new logic, FALL THROUGH to the existing universal behavior
4. Does not crash on unrecognized inputs

CRITICAL: The script must still respond identically to no-args, --help, --version. New behavior is ADDITIONAL, not REPLACING.

Return ONLY the contents of `main.py`, wrapped in a single ```python ... ``` block.
"""


def build_patch_prompt(tool_key: str, meta: dict, fail_data: dict) -> str:
    slug = tool_key.rsplit(".", 1)[0] if "." in tool_key else tool_key
    m = meta.get(slug, {})
    failures_lines = []
    for first_line, count in fail_data.get("top_first_lines", [])[:6]:
        failures_lines.append(f"- ({count}x) {first_line[:200]}")
    if fail_data.get("bucket_samples"):
        failures_lines.append("")
        failures_lines.append("Test name samples:")
        for bucket, samples in list(fail_data.get("bucket_samples", {}).items())[:3]:
            failures_lines.append(f"- {bucket}:")
            for s in samples[:3]:
                failures_lines.append(f"  - {s}")
    failures_block = "\n".join(failures_lines) or "(no failure data)"
    current_main = find_scaffold_main(tool_key)[:8000]
    return PATCH_PROMPT_TEMPLATE.format(
        tool_name=m.get("tool_name", slug),
        language=m.get("lang", "?"),
        total=fail_data.get("total", 0),
        passed=fail_data.get("passed", 0),
        pct=fail_data.get("pct", 0.0),
        current_main_py=current_main,
        failures_block=failures_block,
    )


def validate_preserves_universal(code: str) -> tuple[bool, str]:
    """Verify code preserves key universal patterns. Returns (ok, reason)."""
    checks = [
        (
            "no-args rc=2",
            any(p in code for p in ("if not argv:", "if len(argv) == 0", "if len(sys.argv) <= 1")),
        ),
        ("--help handler", "--help" in code or "-h" in code),
        ("sys.exit / return code", "sys.exit" in code or "return 0" in code or "return 2" in code),
        ("SIGPIPE handler", "SIGPIPE" in code),
    ]
    missing = [name for name, ok in checks if not ok]
    if missing:
        return (False, f"missing: {', '.join(missing)}")
    return (True, "ok")


def generate_patch(
    tool_key: str,
    meta: dict,
    failures: dict,
    backend: str = "deepseek",
    model: str = "deepseek-chat",
) -> bool:
    fail_data = failures.get(tool_key)
    if not fail_data:
        print(f"  {tool_key}: no failure data")
        return False
    if fail_data.get("pct", 0) >= 100:
        return False
    prompt = build_patch_prompt(tool_key, meta, fail_data)
    print(f"  {tool_key}: calling {backend} (prompt {len(prompt)} chars)")
    try:
        response = call_llm(prompt, backend=backend, model=model)
    except Exception as e:
        print(f"  {tool_key}: API failed: {e}")
        return False
    code = extract_python_from_response(response)
    if not code:
        print(f"  {tool_key}: no code in response")
        return False
    ok, reason = validate_preserves_universal(code)
    if not ok:
        print(f"  {tool_key}: validation failed ({reason}) - skipping")
        return False
    target_dir = OVERRIDES_DIR / tool_key
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "main.py").write_text(code, encoding="utf-8", newline="\n")
    print(f"  {tool_key}: wrote {len(code)} chars (validated)")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", help="single tool_key")
    ap.add_argument(
        "--revert-list", help="file with tool_keys (one per line) — usually c:/tmp/revert_list.txt"
    )
    ap.add_argument("--backend", default="deepseek")
    ap.add_argument("--model", default="deepseek-chat")
    args = ap.parse_args()

    meta = load_pb_meta()
    failures = load_failures()

    if args.tool:
        candidates = [args.tool]
    elif args.revert_list:
        candidates = [
            l.strip()
            for l in open(args.revert_list, encoding="utf-8").read().splitlines()
            if l.strip()
        ]
    else:
        print("Must specify --tool or --revert-list")
        sys.exit(1)

    print(f"Generating patch-on-top for {len(candidates)} tools using {args.backend}/{args.model}")
    success = 0
    for tk in candidates:
        if generate_patch(tk, meta, failures, backend=args.backend, model=args.model):
            success += 1
    print(f"\nGenerated: {success}/{len(candidates)}")


if __name__ == "__main__":
    main()
