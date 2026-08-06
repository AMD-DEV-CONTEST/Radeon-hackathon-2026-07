from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .files import atomic_write_text
from .v10_contracts import (
    EvidenceAxis,
    EvidencePointer,
    TodoStatus,
    V10ContractError,
    stable_digest,
)


PROGRAM_SCHEMA = "ProofLaunchCortexXV10ProgramV1"
TASK_PATTERN = re.compile(
    r"^(?P<todo_id>\d{4}) "
    r"\[(?P<base>D/A/I/E)\]"
    r"(?P<breakthrough>\[(?:T|P|X)\])? "
    r"(?P<text>.+?)。?\s*$"
)
WORKSTREAM_PATTERN = re.compile(
    r"^(?:Workstream|Breakthrough) (?P<id>\d{2}) [—-] (?P<title>.+?)\s*$"
)


EXECUTION_WAVES: dict[int, str] = {
    1: "W0_rules_safety_runtime",
    9: "W0_rules_safety_runtime",
    22: "W0_rules_safety_runtime",
    23: "W0_rules_safety_runtime",
    2: "W1_reuse_data_eval",
    3: "W1_reuse_data_eval",
    4: "W1_reuse_data_eval",
    10: "W1_reuse_data_eval",
    11: "W1_reuse_data_eval",
    21: "W1_reuse_data_eval",
    5: "W2_typed_control_plane",
    6: "W2_typed_control_plane",
    7: "W2_typed_control_plane",
    8: "W2_typed_control_plane",
    12: "W2_typed_control_plane",
    18: "W2_typed_control_plane",
    13: "W3_training",
    14: "W3_training",
    15: "W3_training",
    16: "W3_training",
    17: "W3_training",
    19: "W4_media",
    20: "W4_media",
    25: "W5_causal_genome_memory",
    27: "W5_causal_genome_memory",
    33: "W5_causal_genome_memory",
    26: "W6_planning_agency_routing",
    29: "W6_planning_agency_routing",
    30: "W6_planning_agency_routing",
    34: "W6_planning_agency_routing",
    28: "W7_proof_taste_repair",
    31: "W7_proof_taste_repair",
    32: "W7_proof_taste_repair",
    35: "W8_experiment_product",
    36: "W8_experiment_product",
    24: "W9_submission",
}


WORKSTREAM_DEPENDENCIES: dict[int, tuple[int, ...]] = {
    2: (1,),
    3: (1,),
    4: (2, 3),
    9: (1,),
    10: (2, 9),
    11: (9, 10),
    21: (1, 3),
    22: (1, 9),
    23: (1, 2),
    5: (3, 9, 21),
    6: (2, 5, 22),
    7: (5, 6, 21),
    8: (5, 9, 22),
    12: (4, 7, 11),
    18: (5, 6, 8, 21),
    13: (4, 11, 23),
    14: (12, 13),
    15: (13, 14),
    16: (14, 15, 21),
    17: (14, 16, 23),
    19: (13, 17, 21, 23),
    20: (13, 17, 19, 21, 23),
    25: (5, 9, 21),
    27: (8, 10, 21),
    33: (8, 9, 21),
    26: (5, 7, 25),
    29: (6, 7, 21),
    30: (14, 17, 23),
    34: (6, 7, 25, 26),
    28: (19, 20, 22, 27),
    31: (10, 18, 21, 27),
    32: (19, 20, 21, 28, 31),
    35: (9, 21, 25),
    36: (26, 27, 28, 29, 31, 32, 33, 34, 35),
    24: tuple(range(1, 24)) + tuple(range(25, 37)),
}


@dataclass
class TodoRecord:
    todo_id: str
    workstream_id: int
    workstream_title: str
    text: str
    required_axes: tuple[EvidenceAxis, ...]
    execution_wave: str
    dependency_workstreams: tuple[int, ...]
    status: TodoStatus = TodoStatus.NOT_STARTED
    evidence: dict[EvidenceAxis, EvidencePointer] = field(default_factory=dict)
    conclusion: str | None = None

    def attach(self, pointer: EvidencePointer) -> None:
        if pointer.axis not in self.required_axes:
            raise V10ContractError(
                f"{self.todo_id} does not accept {pointer.axis.value} evidence"
            )
        self.evidence[pointer.axis] = pointer
        if self.status == TodoStatus.NOT_STARTED:
            self.status = TodoStatus.IN_PROGRESS

    @property
    def missing_axes(self) -> tuple[EvidenceAxis, ...]:
        return tuple(axis for axis in self.required_axes if axis not in self.evidence)

    def close(self, status: TodoStatus, *, conclusion: str) -> None:
        if status not in {TodoStatus.PASSED, TodoStatus.FALSIFIED}:
            raise V10ContractError("close status must be passed or falsified")
        if self.missing_axes:
            missing = "/".join(axis.value for axis in self.missing_axes)
            raise V10ContractError(
                f"{self.todo_id} cannot close; missing evidence axes {missing}"
            )
        if not conclusion.strip():
            raise V10ContractError("a closure conclusion is required")
        self.status = status
        self.conclusion = conclusion

    def to_dict(self) -> dict[str, Any]:
        return {
            "todo_id": self.todo_id,
            "workstream_id": self.workstream_id,
            "workstream_title": self.workstream_title,
            "text": self.text,
            "required_axes": [axis.value for axis in self.required_axes],
            "execution_wave": self.execution_wave,
            "dependency_workstreams": list(self.dependency_workstreams),
            "status": self.status.value,
            "missing_axes": [axis.value for axis in self.missing_axes],
            "evidence": {
                axis.value: pointer.to_dict()
                for axis, pointer in sorted(
                    self.evidence.items(), key=lambda item: item[0].value
                )
            },
            "conclusion": self.conclusion,
        }


@dataclass
class CortexProgram:
    todos: list[TodoRecord]
    source_sha256: str
    schema: str = PROGRAM_SCHEMA

    @classmethod
    def parse(cls, sources: Sequence[str]) -> CortexProgram:
        todos: list[TodoRecord] = []
        workstreams: dict[int, str] = {}
        current_workstream: tuple[int, str] | None = None
        combined = "\n".join(sources)
        for line in combined.splitlines():
            stripped = line.strip()
            workstream_match = WORKSTREAM_PATTERN.match(stripped)
            if workstream_match:
                current_workstream = (
                    int(workstream_match.group("id")),
                    workstream_match.group("title"),
                )
                workstreams[current_workstream[0]] = current_workstream[1]
                continue
            task_match = TASK_PATTERN.match(stripped)
            if not task_match:
                continue
            if current_workstream is None:
                raise V10ContractError(
                    f"task {task_match.group('todo_id')} has no workstream"
                )
            todo_number = int(task_match.group("todo_id"))
            inferred_workstream = (
                (todo_number - 1) // 50 + 1
                if todo_number <= 1200
                else 25 + (todo_number - 1201) // 25
            )
            if current_workstream[0] != inferred_workstream:
                raise V10ContractError(
                    f"task {todo_number:04d} is under workstream "
                    f"{current_workstream[0]:02d}, expected {inferred_workstream:02d}"
                )
            axes = [
                EvidenceAxis.DISTILLATION,
                EvidenceAxis.ACADEMIC,
                EvidenceAxis.INNOVATION,
                EvidenceAxis.EVIDENCE,
            ]
            breakthrough = task_match.group("breakthrough")
            if todo_number >= 1201:
                if breakthrough is None:
                    raise V10ContractError(
                        f"breakthrough task {todo_number:04d} lacks T/P/X"
                    )
                axes.append(EvidenceAxis(breakthrough[1]))
            elif breakthrough is not None:
                raise V10ContractError(
                    f"base task {todo_number:04d} unexpectedly has T/P/X"
                )
            todos.append(
                TodoRecord(
                    todo_id=f"{todo_number:04d}",
                    workstream_id=current_workstream[0],
                    workstream_title=current_workstream[1],
                    text=task_match.group("text"),
                    required_axes=tuple(axes),
                    execution_wave=EXECUTION_WAVES[current_workstream[0]],
                    dependency_workstreams=WORKSTREAM_DEPENDENCIES.get(
                        current_workstream[0], ()
                    ),
                )
            )
        program = cls(todos=todos, source_sha256=stable_digest(combined))
        program.validate()
        return program

    @classmethod
    def from_files(cls, paths: Sequence[str | Path]) -> CortexProgram:
        return cls.parse(
            [Path(path).read_text(encoding="utf-8") for path in paths]
        )

    def validate(self) -> None:
        expected = [f"{number:04d}" for number in range(1, 1501)]
        actual = [todo.todo_id for todo in self.todos]
        if actual != expected:
            missing = sorted(set(expected) - set(actual))
            duplicates = sorted(
                todo_id for todo_id in set(actual) if actual.count(todo_id) > 1
            )
            raise V10ContractError(
                "program must contain exact ordered ids 0001-1500; "
                f"missing={missing[:5]}, duplicates={duplicates[:5]}"
            )
        workstream_counts: dict[int, int] = {}
        for todo in self.todos:
            workstream_counts[todo.workstream_id] = (
                workstream_counts.get(todo.workstream_id, 0) + 1
            )
        if set(workstream_counts) != set(range(1, 37)):
            raise V10ContractError("program must contain workstreams 01-36")
        invalid_counts = {
            workstream: count
            for workstream, count in workstream_counts.items()
            if count not in ({50} if workstream <= 24 else {25})
        }
        if invalid_counts:
            raise V10ContractError(
                f"workstream task counts are invalid: {invalid_counts}"
            )

    @property
    def summary(self) -> dict[str, int]:
        summary = {status.value: 0 for status in TodoStatus}
        for todo in self.todos:
            summary[todo.status.value] += 1
        return summary

    def ordered_workstreams(self) -> list[dict[str, Any]]:
        grouped: dict[int, list[TodoRecord]] = {}
        for todo in self.todos:
            grouped.setdefault(todo.workstream_id, []).append(todo)
        return sorted(
            (
                {
                    "workstream_id": workstream_id,
                    "title": todos[0].workstream_title,
                    "execution_wave": todos[0].execution_wave,
                    "dependency_workstreams": list(
                        todos[0].dependency_workstreams
                    ),
                    "todo_start": todos[0].todo_id,
                    "todo_end": todos[-1].todo_id,
                    "todo_count": len(todos),
                }
                for workstream_id, todos in grouped.items()
            ),
            key=lambda item: (
                item["execution_wave"],
                item["workstream_id"],
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_sha256": self.source_sha256,
            "truth_policy": {
                "default_status": TodoStatus.NOT_STARTED.value,
                "closure_requires_every_declared_axis": True,
                "falsified_experiment_can_close": True,
                "falsified_experiment_can_enter_product": False,
                "simulated_business_outcomes_are_predicted_only": True,
            },
            "summary": self.summary,
            "execution_order": self.ordered_workstreams(),
            "todos": [todo.to_dict() for todo in self.todos],
        }

    def write(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            target,
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )


def canonical_source_text(sources: Iterable[str]) -> str:
    cleaned = [source.strip() for source in sources if source.strip()]
    if not cleaned:
        raise V10ContractError("at least one non-empty source is required")
    return "\n\n---\n\n".join(cleaned) + "\n"
