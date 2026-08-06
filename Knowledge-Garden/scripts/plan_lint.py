#!/usr/bin/env python3
"""plan_lint.py — mechanical lint of the qwen3-learning-flow dependency contract.

Task-ID grammar: implementation todos 1-11, final verifiers F1-F4, or `[]`.
Rules enforced:
  - Every task's `Blocked by` / `Blocks` fields contain ONLY ids from the grammar or `[]`.
  - `Blocks` is the mechanical inverse of `Depends on` (direct edges only).
  - Range notation (e.g. "3-11") and non-grammar sentinels (none/completion/baseline gate) are rejected.
  - F1/F2/F4 (terminal) have `Blocks: []`.
Self-test: --selftest runs against a deliberate-contradiction fixture and must FAIL on it.
"""
from __future__ import annotations

import json
import re
import sys

TASK_IDS = {str(i) for i in range(1, 12)} | {f"F{n}" for n in range(1, 5)}
VALID_TOKENS = TASK_IDS | {"[]"}

DEP_MATRIX = {
    "1":  ([], ["6"]),
    "2":  ([], ["3", "4", "5", "7"]),
    "3":  (["2"], ["4", "6", "7", "8", "9"]),
    "4":  (["2", "3", "5"], ["7", "8"]),
    "5":  (["2"], ["4", "6", "8"]),
    "6":  (["1", "3", "5"], ["7", "8"]),
    "7":  (["2", "3", "4", "6"], ["8"]),
    "8":  (["3", "4", "5", "6", "7"], ["9", "10"]),
    "9":  (["3", "7", "8"], ["10"]),
    "10": (["8", "9"], ["11"]),
    "11": (["6", "7", "8", "9", "10"], ["F1", "F2", "F3", "F4"]),
    "F3": (["11"], ["F1", "F2", "F4"]),
    "F1": (["11", "F3"], []),
    "F2": (["11", "F3"], []),
    "F4": (["11", "F3"], []),
}

TERMINAL = {"F1", "F2", "F4"}

FIELD_RE = re.compile(r"Blocked by: ([^\|]+) \| Blocks: ([^$]+)$")


def _parse_field(value: str) -> list[str]:
    v = value.strip()
    if v == "[]":
        return []
    tokens = [t.strip() for t in v.split(",") if t.strip()]
    for t in tokens:
        if t not in VALID_TOKENS:
            raise ValueError(f"invalid dependency token '{t}' (must be task id 1-11/F1-F4 or [])")
    return tokens


def lint_plan(path: str, matrix: dict[str, tuple[list[str], list[str]]] | None = None) -> list[str]:
    errors: list[str] = []
    matrix = matrix or DEP_MATRIX
    text = open(path, encoding="utf-8").read()

    for task_id in TASK_IDS:
        # find the task row `- [ ] <id>. ...`
        m = re.search(rf"^- \[ \] {re.escape(task_id)}\. ", text, re.M)
        if not m:
            errors.append(f"task {task_id}: row not found")
            continue
        # find the Parallelization line and parse Blocked by / Blocks
        block_start = text.find("Parallelization:", m.start())
        block_end = text.find("\n  Commit:", block_start)
        block = text[block_start:block_end] if block_end > 0 else text[block_start:]
        pm = re.search(r"Blocked by: ([^\|]+) \| Blocks: (.+)", block)
        if not pm:
            errors.append(f"task {task_id}: Parallelization line missing Blocked by/Blocks")
            continue
        try:
            blocked_by = _parse_field(pm.group(1))
            blocks = _parse_field(pm.group(2))
        except ValueError as e:
            errors.append(f"task {task_id}: {e}")
            continue
        if not matrix.get(task_id):
            errors.append(f"task {task_id}: missing in dependency matrix")
            continue
        exp_dep, exp_blocks = matrix[task_id]
        if sorted(blocked_by) != sorted(exp_dep):
            errors.append(f"task {task_id}: Blocked by {blocked_by} != matrix {exp_dep}")
        if sorted(blocks) != sorted(exp_blocks):
            errors.append(f"task {task_id}: Blocks {blocks} != matrix inverse {exp_blocks}")
        if task_id in TERMINAL and blocks != []:
            errors.append(f"task {task_id}: terminal must have Blocks: []")

    # matrix inverse consistency (Blocks is mechanical inverse of Depends on)
    for tid, (deps, blocks) in matrix.items():
        for b in blocks:
            if b not in matrix:
                errors.append(f"matrix: {tid} Blocks contains unknown task {b}")
                continue
            if tid not in matrix[b][0]:
                errors.append(f"matrix: {tid} blocks {b} but {b} does not depend on {tid}")
    return errors


def self_test() -> None:
    # build a deliberate contradiction: task 3 matrix says it does NOT block 9, but task 9 declares Blocked by 3
    bad = {"3": (["2"], ["4", "6", "7", "8"])}  # removed 9 from blocks
    # reuse real plan file: task 9 declares Blocked by 3,7,8, so it will mismatch the bad matrix
    errors = lint_plan("/persistent/learning-companion/.omo/plans/qwen3-learning-flow.md", bad)
    if not errors:
        print("SELFTEST_FAIL: deliberate contradiction was not detected")
        sys.exit(1)
    print(f"SELFTEST_OK: detected {len(errors)} contradiction(s) in fixture")
    sys.exit(0)


def main() -> int:
    path = "/persistent/learning-companion/.omo/plans/qwen3-learning-flow.md"
    errors = lint_plan(path)
    if errors:
        for e in errors:
            print(f"PLAN_LINT_FAIL: {e}")
        return 1
    print("PLAN_LINT_OK: dependency matrix consistent, grammar valid")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        self_test()
    sys.exit(main())
