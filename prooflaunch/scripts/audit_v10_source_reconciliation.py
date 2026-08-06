#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIRST_300 = Path(
    ROOT / "sources" / "cortex-x-v10-first-300.txt"
)
DEFAULT_SECOND_1200 = Path(
    ROOT / "sources" / "cortex-x-v10-second-1200.txt"
)
DEFAULT_CANONICAL = ROOT / "docs" / "CORTEX_X_V10_1500_TODO.md"
DEFAULT_OUTPUT = (
    ROOT / "evidence" / "v10" / "source-reconciliation-300-plus-1200.json"
)
TODO_RE = re.compile(r"^(?P<id>\d{4})\s+(?P<body>\[D/A/I/E\].+?)\s*$")


@dataclass(frozen=True)
class TodoLine:
    todo_id: int
    text: str
    line: int

    @property
    def canonical_line(self) -> str:
        return f"{self.todo_id:04d} {self.text}"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_todos(path: Path) -> tuple[bytes, list[TodoLine]]:
    payload = path.read_bytes()
    text = payload.decode("utf-8")
    todos: list[TodoLine] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = TODO_RE.match(line.strip())
        if match:
            todos.append(
                TodoLine(
                    todo_id=int(match.group("id")),
                    text=match.group("body").strip(),
                    line=line_number,
                )
            )
    return payload, todos


def duplicate_ids(todos: Iterable[TodoLine]) -> list[int]:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for todo in todos:
        if todo.todo_id in seen:
            duplicates.add(todo.todo_id)
        seen.add(todo.todo_id)
    return sorted(duplicates)


def range_audit(
    todos: list[TodoLine],
    expected_start: int,
    expected_end: int,
) -> dict[str, object]:
    expected = list(range(expected_start, expected_end + 1))
    observed = [todo.todo_id for todo in todos]
    observed_set = set(observed)
    expected_set = set(expected)
    return {
        "expectedStart": expected_start,
        "expectedEnd": expected_end,
        "expectedCount": len(expected),
        "observedCount": len(observed),
        "observedStart": observed[0] if observed else None,
        "observedEnd": observed[-1] if observed else None,
        "missingIds": sorted(expected_set - observed_set),
        "unexpectedIds": sorted(observed_set - expected_set),
        "duplicateIds": duplicate_ids(todos),
        "strictlyOrderedAndContiguous": observed == expected,
    }


def source_descriptor(
    path: Path,
    payload: bytes,
    todos: list[TodoLine],
    expected_start: int,
    expected_end: int,
    semantic_role: str,
) -> dict[str, object]:
    return {
        "semanticRole": semantic_role,
        "path": str(path.resolve()),
        "bytes": len(payload),
        "lineCount": len(payload.decode("utf-8").splitlines()),
        "sha256": sha256_bytes(payload),
        "rangeAudit": range_audit(todos, expected_start, expected_end),
    }


def compare_todos(
    expected: list[TodoLine],
    canonical: list[TodoLine],
) -> dict[str, object]:
    expected_by_id = {todo.todo_id: todo for todo in expected}
    canonical_by_id = {todo.todo_id: todo for todo in canonical}
    all_ids = sorted(set(expected_by_id) | set(canonical_by_id))
    mismatches: list[dict[str, object]] = []
    for todo_id in all_ids:
        source_item = expected_by_id.get(todo_id)
        canonical_item = canonical_by_id.get(todo_id)
        if source_item is None or canonical_item is None:
            mismatches.append(
                {
                    "id": f"{todo_id:04d}",
                    "source": (
                        source_item.canonical_line if source_item else None
                    ),
                    "canonical": (
                        canonical_item.canonical_line
                        if canonical_item
                        else None
                    ),
                    "reason": "missing-side",
                }
            )
        elif source_item.text != canonical_item.text:
            mismatches.append(
                {
                    "id": f"{todo_id:04d}",
                    "source": source_item.canonical_line,
                    "canonical": canonical_item.canonical_line,
                    "reason": "text-mismatch",
                }
            )
    expected_lines = [todo.canonical_line for todo in expected]
    canonical_lines = [todo.canonical_line for todo in canonical]
    return {
        "sourceRequirementSha256": sha256_bytes(
            ("\n".join(expected_lines) + "\n").encode("utf-8")
        ),
        "canonicalRequirementSha256": sha256_bytes(
            ("\n".join(canonical_lines) + "\n").encode("utf-8")
        ),
        "sourceCount": len(expected),
        "canonicalCount": len(canonical),
        "sourceOrder": [todo.todo_id for todo in expected],
        "canonicalOrder": [todo.todo_id for todo in canonical],
        "orderExact": expected_lines == canonical_lines,
        "textMismatchCount": len(mismatches),
        "textMismatches": mismatches,
    }


def build_audit(
    first_300_path: Path,
    second_1200_path: Path,
    canonical_path: Path,
) -> dict[str, object]:
    first_payload, first_todos = read_todos(first_300_path)
    second_payload, second_todos = read_todos(second_1200_path)
    canonical_payload, canonical_todos = read_todos(canonical_path)

    # User-defined semantic order: the second attachment is the 0001–1200
    # foundation and the first attachment is the 1201–1500 extension.
    combined = second_todos + first_todos
    combined_range = range_audit(combined, 1, 1500)
    comparison = compare_todos(combined, canonical_todos)
    canonical_range = range_audit(canonical_todos, 1, 1500)
    passed = bool(
        first_todos
        and second_todos
        and first_todos[0].todo_id == 1201
        and second_todos[0].todo_id == 1
        and first_todos[-1].todo_id == 1500
        and second_todos[-1].todo_id == 1200
        and first_todos[0].todo_id == second_todos[-1].todo_id + 1
        and combined_range["strictlyOrderedAndContiguous"]
        and canonical_range["strictlyOrderedAndContiguous"]
        and comparison["orderExact"]
        and comparison["textMismatchCount"] == 0
    )
    payload: dict[str, object] = {
        "schema": "ProofLaunchV10SourceReconciliationV1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if passed else "fail",
        "truthPolicy": (
            "The 1500-item program is ordered by requirement identity, not "
            "attachment arrival or filename: source 2 supplies 0001–1200, "
            "then source 1 supplies 1201–1500. Completion is never inferred "
            "from source reconciliation; each TODO still requires D/A/I/E "
            "evidence and the independent 200% overdelivery gate."
        ),
        "declaredSourceOrder": [
            {
                "position": 1,
                "attachmentLabel": "second 1200-item document",
                "range": "0001-1200",
            },
            {
                "position": 2,
                "attachmentLabel": "first 300-item document",
                "range": "1201-1500",
            },
        ],
        "sources": {
            "firstAttachment300": source_descriptor(
                first_300_path,
                first_payload,
                first_todos,
                1201,
                1500,
                "V10 breakthrough extension; executes after the 1200-item base",
            ),
            "secondAttachment1200": source_descriptor(
                second_1200_path,
                second_payload,
                second_todos,
                1,
                1200,
                "V9 base program; executes before the 300-item extension",
            ),
            "canonicalProgram": source_descriptor(
                canonical_path,
                canonical_payload,
                canonical_todos,
                1,
                1500,
                "repository canonical requirement document",
            ),
        },
        "combinedRangeAudit": combined_range,
        "canonicalRangeAudit": canonical_range,
        "comparison": comparison,
        "completionEffect": {
            "requirementsReconciled": passed,
            "todosClosedByThisAudit": 0,
            "gpuClaimsClosedByThisAudit": 0,
            "externalClaimsClosedByThisAudit": 0,
        },
    }
    canonical_for_hash = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["auditSha256"] = sha256_bytes(canonical_for_hash)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile the user-authoritative 300+1200 V10 sources."
    )
    parser.add_argument("--first-300", type=Path, default=DEFAULT_FIRST_300)
    parser.add_argument("--second-1200", type=Path, default=DEFAULT_SECOND_1200)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = build_audit(args.first_300, args.second_1200, args.canonical)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": audit["status"],
                "output": str(args.output),
                "auditSha256": audit["auditSha256"],
                "sourceCounts": {
                    "first300": audit["sources"]["firstAttachment300"][
                        "rangeAudit"
                    ]["observedCount"],
                    "second1200": audit["sources"]["secondAttachment1200"][
                        "rangeAudit"
                    ]["observedCount"],
                },
                "exact": audit["comparison"]["orderExact"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
