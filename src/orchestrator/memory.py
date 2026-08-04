"""Multi-turn conversation memory for the agent."""


class ConversationMemory:
    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self.turns: list[dict] = []

    def add(self, role: str, content: str):
        self.turns.append({"role": role, "content": content})
        self.turns = self.turns[-self.max_turns:]

    def as_messages(self) -> list[dict]:
        return self.turns
