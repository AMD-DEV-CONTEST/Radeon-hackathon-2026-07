from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


RUNNING_TURN_STATUS = "running"
SUPERSEDED_TURN_STATUS = "stopped"


def supersede_running_turns(
    turns: Iterable[Any],
    *,
    updated_at: str,
    keep: Any | None = None,
) -> list[Any]:
    changed: list[Any] = []
    for turn in turns:
        if turn is keep or str(getattr(turn, "status", "") or "") != RUNNING_TURN_STATUS:
            continue
        turn.status = SUPERSEDED_TURN_STATUS
        turn.updated_at = updated_at
        changed.append(turn)
    return changed


def normalize_running_turn_sequence(turns: Sequence[Any], *, updated_at: str) -> list[Any]:
    if len(turns) <= 1:
        return []
    return supersede_running_turns(turns[:-1], updated_at=updated_at)


def stop_unidentified_running_turns(
    turns: Iterable[Any],
    *,
    updated_at: str,
) -> list[Any]:
    changed: list[Any] = []
    for turn in turns:
        request_id = str(getattr(turn, "request_id", "") or "").strip()
        if request_id or str(getattr(turn, "status", "") or "") != RUNNING_TURN_STATUS:
            continue
        turn.status = SUPERSEDED_TURN_STATUS
        turn.updated_at = updated_at
        changed.append(turn)
    return changed
