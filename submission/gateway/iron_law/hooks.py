"""ILS lifecycle hooks — v2.1 structured logging (non-blocking)."""
from __future__ import annotations

from typing import Any

from iron_law.logging import ils_log


class HookBlockError(Exception):
    """Raised by hooks that need to block task progression."""
    def __init__(self, rule: int, message: str):
        self.rule = rule
        self.message = message
        super().__init__(f"[Hook Block Rule {rule}] {message}")


def on_intake(intent_packet: dict[str, Any]) -> None:
    """Called when a task enters the ILS intake pipeline."""
    ils_log.info(
        "ILS_G001_intake",
        task_id=intent_packet.get("task_id"),
        normalized_intent=str(intent_packet.get("normalized_intent", ""))[:120],
        confidence=intent_packet.get("confidence"),
        has_target_object=bool(intent_packet.get("target_object")),
    )


def on_dispatch(task_id: str, agent_id: str, required_caps: dict[str, Any], ownership_conflicts: list[dict[str, Any]] | None = None) -> None:
    """Called when a task is dispatched to an agent."""
    ils_log.info(
        "ILS_G004_dispatch",
        task_id=task_id,
        agent_id=agent_id,
        required_caps=required_caps,
    )


def on_completion(task_id: str, evidence: dict[str, Any], result: str) -> None:
    """Called when a task reports completion."""
    ils_log.info(
        "ILS_G005_completion",
        task_id=task_id,
        result=result,
        evidence_types=list(evidence.keys()),
        artifact_count=len(evidence.get("artifact_uris", [])),
    )
