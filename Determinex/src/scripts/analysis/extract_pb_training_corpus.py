#!/usr/bin/env python3
"""Extract ProgramBench training corpus from _extracted_tests/.

For each PB tool, for each test branch, for each test:
  - Read the test source code (`tests/test_*.py`)
  - Read every fixture in `test_resources/` (golden expected outputs +
    any input files the test passes via stdin/files)
  - Parse test source to find which fixtures it reads / what command
    args it invokes the binary with
  - Emit one training example per test that pairs:
      * The intent (system prompt: "implement a tool that passes tests")
      * The test specification (user prompt: test source + fixtures)
      * The expected output (assistant: golden + impl hint)

Output: corpus/programbench/training_corpus/pb_corpus.jsonl
   plus per-tool shards in corpus/programbench/training_corpus/by_tool/

This becomes training data for LoRA fine-tunes of determinex-engineer /
observer / sentinel — closing the loop so trained models implement PB
tools natively (compiler-validated training pipeline, the Determinex core
methodology).

Run:
  python scripts/analysis/extract_pb_training_corpus.py
  python scripts/analysis/extract_pb_training_corpus.py --tool kyoh86__richgo.313114f
  python scripts/analysis/extract_pb_training_corpus.py --min-fixture-size 1 --max-fixture-bytes 4000
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTRACTED = Path("T:/determinex-programbench/_extracted_tests")
CORPUS_OUT = ROOT / "corpus" / "programbench" / "training_corpus"
CORPUS_OUT.mkdir(parents=True, exist_ok=True)
BY_TOOL_DIR = CORPUS_OUT / "by_tool"
BY_TOOL_DIR.mkdir(parents=True, exist_ok=True)


SYSTEM_PROMPT = (
    "You are a Determinex agent implementing CLI tools to pass byte-exact "
    "behavioral tests. When given a test specification and golden expected "
    "outputs, you produce a Python implementation that the test will pass."
)


def safe_read(p: Path, max_bytes: int = 8000) -> str | None:
    try:
        b = p.read_bytes()
        if len(b) > max_bytes:
            b = b[:max_bytes] + b"\n... [TRUNCATED]"
        # Try text decode
        try:
            return b.decode("utf-8")
        except UnicodeDecodeError:
            # Show as hex preview for binary
            return f"<binary {len(b)} bytes, hex preview: {b[:64].hex()}>"
    except Exception:
        return None


def find_test_functions(test_file: Path) -> list[dict]:
    """Parse a test file's AST and extract each test function source.

    Returns list of {name, source, decorators}.
    """
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
            # Find end line: ast doesn't give end_lineno on older Python but 3.8+ does
            end = getattr(node, "end_lineno", None) or start + 30
            lines = src.splitlines()[start:end]
            out.append(
                {
                    "name": node.name,
                    "source": "\n".join(lines)[:3000],
                }
            )
    return out


def find_fixture_references(test_source: str) -> list[str]:
    """Heuristically extract fixture file names referenced in test source.

    Looks for: 'RESOURCES / "X"', "*.golden", 'test_resources/...'
    """
    refs = set()
    # Path / "filename" pattern
    for m in re.finditer(r'/\s*["\'](\w+\.\w+)["\']', test_source):
        refs.add(m.group(1))
    # .read_text() / .read_bytes() on Path
    for m in re.finditer(r'["\']([\w_./-]+\.golden)["\']', test_source):
        refs.add(m.group(1).split("/")[-1])
    for m in re.finditer(r'["\']([\w_./-]+\.txt)["\']', test_source):
        refs.add(m.group(1).split("/")[-1])
    return sorted(refs)


def extract_branch(tool_slug: str, branch_dir: Path, max_fixture_bytes: int) -> list[dict]:
    """Extract all training examples from one test branch."""
    eval_dir = branch_dir / "eval"
    if not eval_dir.is_dir():
        return []
    tests_dir = eval_dir / "tests"
    if not tests_dir.is_dir():
        return []

    # Map of all fixture files by basename — search BOTH test_resources/ and tests/golden/
    fixture_files = {}
    for search_root in (eval_dir / "test_resources", tests_dir):
        if search_root.is_dir():
            for p in search_root.rglob("*"):
                if p.is_file():
                    fixture_files[p.name] = p

    # Also map by relative path for tests that use longer references
    fixture_by_path = {}
    for search_root in (eval_dir / "test_resources", tests_dir):
        if search_root.is_dir():
            for p in search_root.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(eval_dir).as_posix()
                    fixture_by_path[rel] = p

    examples = []
    for test_file in tests_dir.glob("test_*.py"):
        funcs = find_test_functions(test_file)
        for fn in funcs:
            # Find fixture references in this function
            refs = find_fixture_references(fn["source"])
            # Try to find golden files specifically (these are the "answers")
            golden_refs = [r for r in refs if r.endswith(".golden") or "golden" in r.lower()]
            other_refs = [r for r in refs if r not in golden_refs]

            # Build fixture blocks for user message (input fixtures + small goldens for context)
            fixture_blocks = []
            for ref in (golden_refs + other_refs)[:5]:
                if ref in fixture_files:
                    content = safe_read(fixture_files[ref], max_fixture_bytes)
                    if content:
                        fixture_blocks.append(f"### {ref}\n```\n{content[:max_fixture_bytes]}\n```")

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
                user_msg_parts.append("")
                user_msg_parts.append("## Referenced fixtures")
                user_msg_parts.append("")
                user_msg_parts.extend(fixture_blocks)

            # Assistant answer: the GOLDEN file content if we have one, else a generic hint
            # The golden IS what the tool must produce — that's the training signal.
            assistant_content = None
            primary_golden = None
            for ref in golden_refs:
                if ref in fixture_files:
                    content = safe_read(fixture_files[ref], max_fixture_bytes * 2)
                    if content and not content.startswith("<binary"):
                        primary_golden = (ref, content)
                        break

            if primary_golden:
                ref, content = primary_golden
                assistant_content = (
                    f"To pass this test, the tool when invoked with the test's arguments "
                    f"must produce output matching `{ref}`:\n\n"
                    f"```\n{content}\n```"
                )
            else:
                # Extract assertions for a behaviorally-precise hint
                assertions = re.findall(r"assert .+", fn["source"])[:5]
                if assertions:
                    assistant_content = (
                        f"To pass test '{fn['name']}', the tool must satisfy these assertions:\n"
                        + "\n".join(f"  - {a}" for a in assertions)
                    )
                else:
                    assistant_content = (
                        f"Test '{fn['name']}' has no extractable assertions; "
                        f"see source for behavioral expectations."
                    )

            example = {
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
                    "fixtures_referenced": refs,
                    "golden_used": primary_golden[0] if primary_golden else None,
                },
            }
            examples.append(example)
    return examples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", help="single tool slug (e.g. kyoh86__richgo.313114f)")
    ap.add_argument("--max-fixture-bytes", type=int, default=2000)
    ap.add_argument(
        "--all", action="store_true", help="process all 194 tools (default if no --tool)"
    )
    args = ap.parse_args()

    if not EXTRACTED.is_dir():
        print(f"ERROR: {EXTRACTED} does not exist")
        return

    if args.tool:
        tools = [args.tool]
    else:
        tools = sorted(d.name for d in EXTRACTED.iterdir() if d.is_dir())
    print(f"Processing {len(tools)} tools")

    total_examples = 0
    aggregate_path = CORPUS_OUT / "pb_corpus.jsonl"
    with aggregate_path.open("w", encoding="utf-8", newline="\n") as agg:
        for tool_slug in tools:
            tool_dir = EXTRACTED / tool_slug
            if not tool_dir.is_dir():
                continue
            tool_examples = []
            for branch in tool_dir.iterdir():
                if not branch.is_dir():
                    continue
                tool_examples.extend(extract_branch(tool_slug, branch, args.max_fixture_bytes))
            # Per-tool shard
            shard = BY_TOOL_DIR / f"{tool_slug}.jsonl"
            with shard.open("w", encoding="utf-8", newline="\n") as f:
                for ex in tool_examples:
                    f.write(json.dumps(ex, ensure_ascii=False) + "\n")
            # Aggregate
            for ex in tool_examples:
                agg.write(json.dumps(ex, ensure_ascii=False) + "\n")
            total_examples += len(tool_examples)
            print(f"  {tool_slug}: {len(tool_examples)} examples")
    print()
    print(f"=== TOTAL: {total_examples} training examples ===")
    print(f"Aggregate: {aggregate_path}")
    print(f"Per-tool shards: {BY_TOOL_DIR}")


if __name__ == "__main__":
    main()
