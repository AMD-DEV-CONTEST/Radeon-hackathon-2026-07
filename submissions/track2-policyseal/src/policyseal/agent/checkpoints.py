from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from policyseal.agent.schemas import ClassificationOutcome, ReviewIntent


@dataclass(frozen=True, slots=True)
class ClassificationCheckpoint:
    task_id: str
    revision_id: str
    outcomes: tuple[ClassificationOutcome, ...]
    saved_at: datetime


class TaskCheckpointStore:
    """Stores only redacted terminal outcomes, never source text or model prompts."""

    def __init__(self) -> None:
        self._checkpoints: dict[tuple[str, str], ClassificationCheckpoint] = {}

    def save(
        self,
        task_id: str,
        revision_id: str,
        outcomes: tuple[ClassificationOutcome, ...],
    ) -> ClassificationCheckpoint:
        if not task_id.strip() or not revision_id.strip():
            raise ValueError("task and revision IDs are required")
        checkpoint = ClassificationCheckpoint(
            task_id=task_id,
            revision_id=revision_id,
            outcomes=outcomes,
            saved_at=datetime.now(UTC),
        )
        self._checkpoints[(task_id, revision_id)] = checkpoint
        return checkpoint

    def load(self, task_id: str, revision_id: str) -> ClassificationCheckpoint:
        try:
            return self._checkpoints[(task_id, revision_id)]
        except KeyError as error:
            raise KeyError("task-local classification checkpoint not found") from error

    def delete_task(self, task_id: str) -> None:
        for key in tuple(self._checkpoints):
            if key[0] == task_id:
                del self._checkpoints[key]


@dataclass(frozen=True, slots=True)
class CopilotTurnCheckpoint:
    turn_number: int
    intent: ReviewIntent
    response_text: str
    cited_locations: tuple[str, ...]
    cited_rule_ids: tuple[str, ...]
    cited_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CopilotThreadCheckpoint:
    thread_id: str
    task_id: str
    revision_id: str
    display_reference: str
    turns: tuple[CopilotTurnCheckpoint, ...] = ()


class CopilotCheckpointStore:
    """Task-isolated conversation state containing no user prompts or source values."""

    def __init__(self) -> None:
        self._threads: dict[str, CopilotThreadCheckpoint] = {}

    def start(
        self,
        thread_id: str,
        task_id: str,
        revision_id: str,
        *,
        display_reference: str | None = None,
    ) -> CopilotThreadCheckpoint:
        if thread_id in self._threads:
            raise ValueError("Copilot thread already exists")
        checkpoint = CopilotThreadCheckpoint(
            thread_id=thread_id,
            task_id=task_id,
            revision_id=revision_id,
            display_reference=display_reference or task_id,
        )
        self._threads[thread_id] = checkpoint
        return checkpoint

    def load(self, thread_id: str, *, task_id: str) -> CopilotThreadCheckpoint:
        try:
            checkpoint = self._threads[thread_id]
        except KeyError as error:
            raise KeyError("Copilot thread does not exist") from error
        if checkpoint.task_id != task_id:
            raise KeyError("Copilot thread is isolated to another task")
        return checkpoint

    def append(
        self,
        thread_id: str,
        *,
        task_id: str,
        turn: CopilotTurnCheckpoint,
    ) -> CopilotThreadCheckpoint:
        checkpoint = self.load(thread_id, task_id=task_id)
        if turn.turn_number != len(checkpoint.turns) + 1:
            raise ValueError("Copilot turn sequence is not contiguous")
        updated = CopilotThreadCheckpoint(
            thread_id=checkpoint.thread_id,
            task_id=checkpoint.task_id,
            revision_id=checkpoint.revision_id,
            display_reference=checkpoint.display_reference,
            turns=checkpoint.turns + (turn,),
        )
        self._threads[thread_id] = updated
        return updated

    def delete_task(self, task_id: str) -> None:
        for thread_id in tuple(self._threads):
            if self._threads[thread_id].task_id == task_id:
                del self._threads[thread_id]
