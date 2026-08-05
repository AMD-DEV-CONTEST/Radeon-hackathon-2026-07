from __future__ import annotations

from app.services.storage import SQLiteStorage


class MemoryAgent:
    def __init__(self, storage: SQLiteStorage) -> None:
        self.storage = storage

    def run(self, conversation_id: str, query: str) -> dict[str, object]:
        recent_messages = self.storage.get_recent_messages(conversation_id, limit=6)
        related_memories = self.storage.search_memories(query, limit=4)
        recent_context = [
            f"{message['role']}: {message['content'][:180]}" for message in recent_messages
        ]
        memory_context = [memory["content"] for memory in related_memories]
        return {
            "recent_context": recent_context,
            "memory_context": memory_context,
        }

    def remember(self, conversation_id: str, user_message: str, assistant_message: str) -> None:
        compact = f"User intent: {user_message[:180]} | Assistant outcome: {assistant_message[:220]}"
        self.storage.add_memory(compact, kind="conversation", conversation_id=conversation_id, score=0.5)
