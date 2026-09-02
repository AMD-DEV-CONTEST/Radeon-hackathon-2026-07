#!/usr/bin/env python3
"""Validate the UI-2 task-workbench lifecycle mirror against the backend.

The frontend keeps a *display-only* mirror of the task state machine in
``web/src/api/dto.ts`` (``TASK_ALLOWED_TRANSITIONS`` plus the
``PhaseFTaskStatus`` union) so the UI can offer only legal target statuses.
The server remains the single authority; this script guarantees the mirror
never drifts from the backend source of truth:

* ``app/schemas/task_sql.py::ALLOWED_TRANSITIONS`` (transition graph)
* ``app/schemas/models.py::PhaseFTaskStatus`` (status enum)

Usage::

    python scripts/validate_task_ui.py

Exits non-zero with a readable report when a mismatch is found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DTO_PATH = REPO_ROOT / "web" / "src" / "api" / "dto.ts"

sys.path.insert(0, str(REPO_ROOT))

from app.schemas.models import PhaseFTaskStatus  # noqa: E402
from app.schemas.task_sql import ALLOWED_TRANSITIONS  # noqa: E402


def parse_frontend_statuses(source: str) -> list[str]:
    """Extract the PhaseFTaskStatus string-literal union from dto.ts."""
    match = re.search(
        r"export type PhaseFTaskStatus\s*=\s*((?:\s*\|\s*'[a-z_]+')+)",
        source,
    )
    if not match:
        raise ValueError("PhaseFTaskStatus union not found in dto.ts")
    return re.findall(r"'([a-z_]+)'", match.group(1))


def parse_frontend_transitions(source: str) -> dict[str, list[str]]:
    """Extract the TASK_ALLOWED_TRANSITIONS record literal from dto.ts."""
    match = re.search(
        r"export const TASK_ALLOWED_TRANSITIONS[^=]*=\s*\{(.*?)\n\}",
        source,
        re.DOTALL,
    )
    if not match:
        raise ValueError("TASK_ALLOWED_TRANSITIONS not found in dto.ts")
    transitions: dict[str, list[str]] = {}
    for key, values in re.findall(
        r"^\s*([a-z_]+):\s*\[([^\]]*)\]", match.group(1), re.MULTILINE
    ):
        transitions[key] = re.findall(r"'([a-z_]+)'", values)
    return transitions


def main() -> int:
    errors: list[str] = []
    source = DTO_PATH.read_text(encoding="utf-8")

    backend_statuses = [status.value for status in PhaseFTaskStatus]
    frontend_statuses = parse_frontend_statuses(source)
    if frontend_statuses != backend_statuses:
        errors.append(
            "PhaseFTaskStatus mismatch:\n"
            f"  backend : {backend_statuses}\n"
            f"  frontend: {frontend_statuses}"
        )

    frontend_transitions = parse_frontend_transitions(source)
    backend_transitions = {key: list(values) for key, values in ALLOWED_TRANSITIONS.items()}
    if frontend_transitions != backend_transitions:
        for key in sorted(set(backend_transitions) | set(frontend_transitions)):
            backend_edges = backend_transitions.get(key)
            frontend_edges = frontend_transitions.get(key)
            if backend_edges != frontend_edges:
                errors.append(
                    f"Transition mismatch for '{key}': "
                    f"backend={backend_edges} frontend={frontend_edges}"
                )

    if errors:
        print("Task UI lifecycle validation FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        "Task UI lifecycle validation PASSED: "
        f"{len(frontend_statuses)} statuses, "
        f"{sum(len(v) for v in frontend_transitions.values())} transitions in sync."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
