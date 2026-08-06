from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ConversationMemory:
    max_turns: int = 20
    turns: list[ConversationTurn] = field(default_factory=list)

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append(ConversationTurn(role=role, content=content))
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def to_messages(self) -> list[dict]:
        return [{"role": t.role, "content": t.content} for t in self.turns]

    def clear(self) -> None:
        self.turns.clear()
