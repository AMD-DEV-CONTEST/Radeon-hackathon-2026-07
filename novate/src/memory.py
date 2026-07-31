"""
Local, in-process multi-turn conversation memory.

Deliberately simple and dependency-light: a bounded deque of turns kept in
RAM for the life of the session. Nothing is written to disk or sent
anywhere, which keeps it consistent with Nova's privacy-first design.
Swap this for a persisted store (e.g. SQLite) if cross-session memory is
ever needed — the interface (`add_turn` / `as_messages`) would stay the same.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import config


@dataclass
class Turn:
    role: str  # "user" or "assistant"
    content: str


class ConversationMemory:
    """Bounded window of the most recent conversation turns."""

    def __init__(self, max_turns: int = config.MEMORY_MAX_TURNS) -> None:
        # max_turns counts user+assistant pairs, so keep 2x messages
        self._turns: deque[Turn] = deque(maxlen=max_turns * 2)

    def add_turn(self, role: str, content: str) -> None:
        self._turns.append(Turn(role=role, content=content))

    def as_messages(self) -> list[dict]:
        """Return turns formatted for the LLM chat API."""
        return [{"role": t.role, "content": t.content} for t in self._turns]

    def clear(self) -> None:
        self._turns.clear()

    def __len__(self) -> int:
        return len(self._turns)
