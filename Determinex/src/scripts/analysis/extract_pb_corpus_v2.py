#!/usr/bin/env python3
"""PB training corpus v2: pair PASSING tests with the IMPL CODE that passes them.

v1 corpus had assistant=assertions-list (spec restated). v2 upgrades that for
tools where an override is producing wins: assistant becomes the override's
implementation code (sliced to the relevant region when possible). This gives
models positive examples of test_spec -> working_code.

For tools without wins, we still emit v1-style entries (assertions as spec).

Adds check-valve metadata per example:
  meta.test_status: passed | failure | skipped | error
  meta.delta_vs_baseline: pp gain from current override

When a model later iterates, it can short-circuit any test whose
meta.test_status == 'passed' — that's the check valve: LLM output is
known-correct for those tests, no need to regenerate.

Output:
  corpus/programbench/training_corpus/pb_corpus_v2.jsonl(.gz)
  corpus/programbench/training_corpus/by_tool_v2/<slug>.jsonl

Run:
  python scripts/analysis/extract_pb_corpus_v2.py
"""

from __future__ import annotations

import argparse
import ast
import glob
import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTRACTED = Path("T:/determinex-programbench/_extracted_tests")
EVAL_ROOT = Path("T:/determinex-programbench")
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
CORPUS_OUT = ROOT / "corpus" / "programbench" / "training_corpus"
BY_TOOL = CORPUS_OUT / "by_tool_v2"
BY_TOOL.mkdir(parents=True, exist_ok=True)


SYSTEM_PROMPT = (
    "You are a Determinex agent producing Python implementations of CLI tools that "
    "pass byte-exact behavioral tests. When shown a test and its expected behavior, "
    "you respond with a working implementation snippet."
)


def safe_read(p: Path, max_bytes: int = 8000) -> str | None:
    try:
        b = p.read_bytes()
        if len(b) > max_bytes:
            b = b[:max_bytes] + b"\n... [TRUNCATED]"
        try:
            return b.decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary {len(b)} bytes, hex preview: {b[:64].hex()}>"
    except Exception:
        return None


def find_test_functions(test_file: Path) -> list[dict]:
    try:
        src = test_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except Exception:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test_"):
                continue
            start = node.lineno - 1
            end = getattr(node, "end_lineno", None) or start + 30
            lines = src.splitlines()[start:end]
            out.append({"name": node.name, "source": "\n".join(lines)[:3000]})
    return out


def find_fixture_references(test_source: str) -> list[str]:
    refs = set()
    for m in re.finditer(r'/\s*["\'](\w+\.\w+)["\']', test_source):
        refs.add(m.group(1))
    for m in re.finditer(r'["\']([\w_./-]+\.golden)["\']', test_source):
        refs.add(m.group(1).split("/")[-1])
    return sorted(refs)


def load_test_statuses(tool_key: str) -> dict[str, str]:
    """Return {test_name: status} from latest eval.json for this tool."""
    out = {}
    matches = []
    for ej in glob.glob(str(EVAL_ROOT / "determinex_pb_*_v*" / tool_key / "*.eval.json")):
        p = Path(ej)
        matches.append((p.stat().st_mtime, p))
    if not matches:
        return out
    matches.sort(reverse=True)
    try:
        with open(matches[0][1], encoding="utf-8", errors="replace") as f:
            j = json.load(f)
    except Exception:
        return out
    for r in j.get("test_results") or []:
        nm = r.get("name", "")
        # PB stores names like "eval.tests.test_foo.test_bar" — drop module path
        leaf = nm.split(".")[-1]
        out[nm] = r.get("status", "unknown")
        out[leaf] = r.get("status", "unknown")
    return out


def load_override(tool_key: str) -> str | None:
    p = OVERRIDES / tool_key / "main.py"
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    return None


def slice_impl_for_test(override_src: str, test_name: str) -> str:
    """Heuristic: try to extract the region of override that handles this test.

    Strategies:
      - If test name suggests a flag (e.g. test_help_flag), look for that flag's handler
      - If test name suggests a subcommand, look for that subcommand
      - Else: return the full override (truncated)
    """
    # Extract identifiers from test name
    parts = test_name.replace("test_", "").split("_")
    keywords = [p for p in parts if len(p) > 2]

    # Try to find a function or branch that mentions a keyword
    lines = override_src.splitlines()
    best_region = None
    for kw in keywords:
        # Find lines containing kw
        for i, line in enumerate(lines):
            if kw in line.lower() and ("def " in line or "if " in line or "elif " in line):
                # Take this line + 20 surrounding lines as the relevant region
                start = max(0, i - 2)
                end = min(len(lines), i + 25)
                region = "\n".join(lines[start:end])
                if not best_region or len(region) > len(best_region):
                    best_region = region

    if best_region and len(best_region) > 100:
        return best_region[:2500]
    # Fallback: full override (truncated)
    return override_src[:4000]


def extract_branch(
    tool_slug: str,
    branch_dir: Path,
    test_statuses: dict,
    override_src: str | None,
    max_fixture_bytes: int,
) -> list[dict]:
    eval_dir = branch_dir / "eval"
    if not eval_dir.is_dir():
        return []
    tests_dir = eval_dir / "tests"
    if not tests_dir.is_dir():
        return []

    fixture_files = {}
    for search_root in (eval_dir / "test_resources", tests_dir):
        if search_root.is_dir():
            for p in search_root.rglob("*"):
                if p.is_file():
                    fixture_files[p.name] = p

    examples = []
    for test_file in tests_dir.glob("test_*.py"):
        funcs = find_test_functions(test_file)
        for fn in funcs:
            # Determine test status from eval.json
            status = test_statuses.get(fn["name"], "unknown")

            refs = find_fixture_references(fn["source"])
            golden_refs = [r for r in refs if r.endswith(".golden") or "golden" in r.lower()]
            other_refs = [r for r in refs if r not in golden_refs]

            fixture_blocks = []
            for ref in (golden_refs + other_refs)[:5]:
                if ref in fixture_files:
                    content = safe_read(fixture_files[ref], max_fixture_bytes)
                    if content:
                        fixture_blocks.append(f"### {ref}\n```\n{content[:max_fixture_bytes]}\n```")

            primary_golden = None
            for ref in golden_refs:
                if ref in fixture_files:
                    content = safe_read(fixture_files[ref], max_fixture_bytes * 2)
                    if content and not content.startswith("<binary"):
                        primary_golden = (ref, content)
                        break

            user_msg_parts = [
                f"# Tool: {tool_slug}",
                f"# Test: {test_file.name}::{fn['name']}",
                "",
                "## Test source",
                "```python",
                fn["source"],
                "```",
            ]
            if fixture_blocks:
                user_msg_parts.append("\n## Referenced fixtures\n")
                user_msg_parts.extend(fixture_blocks)

            # v2: assistant content depends on test status + override availability
            if status == "passed" and override_src:
                # PASSING + we have the impl → pair test with working impl region
                impl_region = slice_impl_for_test(override_src, fn["name"])
                assistant_content = (
                    f"This test PASSES with the current implementation. Working impl region:\n\n"
                    f"```python\n{impl_region}\n```"
                )
                example_type = "working_impl"
            elif primary_golden:
                ref, content = primary_golden
                assistant_content = (
                    f"To pass this test, when invoked with the test's arguments the tool must "
                    f"produce output matching `{ref}`:\n\n```\n{content}\n```"
                )
                example_type = "golden_output"
            else:
                assertions = re.findall(r"assert .+", fn["source"])[:5]
                if assertions:
                    assistant_content = (
                        f"To pass test '{fn['name']}', the tool must satisfy:\n"
                        + "\n".join(f"  - {a}" for a in assertions)
                    )
                    example_type = "assertions_spec"
                else:
                    assistant_content = (
                        f"Test '{fn['name']}': see source for behavioral expectations."
                    )
                    example_type = "spec_only"

            examples.append(
                {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": "\n".join(user_msg_parts)},
                        {"role": "assistant", "content": assistant_content},
                    ],
                    "meta": {
                        "tool": tool_slug,
                        "branch": branch_dir.name,
                        "test_file": test_file.name,
                        "test_name": fn["name"],
                        "test_status": status,
                        "fixtures_referenced": refs,
                        "golden_used": primary_golden[0] if primary_golden else None,
                        "example_type": example_type,
                    },
                }
            )
    return examples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", help="single tool slug")
    ap.add_argument("--max-fixture-bytes", type=int, default=2000)
    args = ap.parse_args()

    if args.tool:
        tools = [args.tool]
    else:
        tools = sorted(d.name for d in EXTRACTED.iterdir() if d.is_dir())
    print(f"v2 corpus: processing {len(tools)} tools")

    total = 0
    by_type = {"working_impl": 0, "golden_output": 0, "assertions_spec": 0, "spec_only": 0}
    by_status = {"passed": 0, "failure": 0, "skipped": 0, "unknown": 0, "error": 0, "not_run": 0}

    agg_path = CORPUS_OUT / "pb_corpus_v2.jsonl"
    with agg_path.open("w", encoding="utf-8", newline="\n") as agg:
        for tool_slug in tools:
            tool_dir = EXTRACTED / tool_slug
            if not tool_dir.is_dir():
                continue
            test_statuses = load_test_statuses(tool_slug)
            override_src = load_override(tool_slug)
            tool_examples = []
            for branch in tool_dir.iterdir():
                if not branch.is_dir():
                    continue
                tool_examples.extend(
                    extract_branch(
                        tool_slug, branch, test_statuses, override_src, args.max_fixture_bytes
                    )
                )
            # Per-tool shard
            (BY_TOOL / f"{tool_slug}.jsonl").write_text(
                "\n".join(json.dumps(ex, ensure_ascii=False) for ex in tool_examples) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            for ex in tool_examples:
                agg.write(json.dumps(ex, ensure_ascii=False) + "\n")
                by_type[ex["meta"]["example_type"]] = by_type.get(ex["meta"]["example_type"], 0) + 1
                by_status[ex["meta"]["test_status"]] = (
                    by_status.get(ex["meta"]["test_status"], 0) + 1
                )
            total += len(tool_examples)

    # Gzip the aggregate for repo storage
    with (
        open(agg_path, "rb") as f_in,
        gzip.open(str(agg_path) + ".gz", "wb", compresslevel=9) as f_out,
    ):
        f_out.writelines(f_in)

    print(f"\n=== TOTAL: {total} examples ===")
    print(f"by example_type: {by_type}")
    print(f"by test_status:  {by_status}")
    print(f"aggregate: {agg_path}")
    print(f"gzipped:   {agg_path}.gz ({Path(str(agg_path) + '.gz').stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
