"""
Short-Term Agent Memory — Per-Session Ring Buffer
Stores the last N exchanges within a single studio session.
"""
from collections import deque
from typing import List, Dict, Any
import time

MAX_MESSAGES = 10   # keep last 10 exchanges per session


class ShortTermMemory:
    """
    In-process session memory keyed by (child_id, session_id).
    Thread-safe for single-process FastAPI (asyncio event loop).
    """
    def __init__(self):
        self._store: Dict[str, deque] = {}
        self._meta: Dict[str, Dict[str, Any]] = {}

    def _key(self, child_id: str, session_id: str) -> str:
        return f"{child_id}:{session_id}"

    def push(self, child_id: str, session_id: str, role: str, content: str):
        k = self._key(child_id, session_id)
        if k not in self._store:
            self._store[k] = deque(maxlen=MAX_MESSAGES)
            self._meta[k] = {"started_at": time.time(), "hint_count": 0}
        self._store[k].append({"role": role, "content": content, "ts": time.time()})
        if role == "assistant":
            self._meta[k]["hint_count"] += 1

    def get_history(self, child_id: str, session_id: str) -> List[Dict]:
        k = self._key(child_id, session_id)
        return list(self._store.get(k, []))

    def get_hint_count(self, child_id: str, session_id: str) -> int:
        k = self._key(child_id, session_id)
        return self._meta.get(k, {}).get("hint_count", 0)

    def clear_session(self, child_id: str, session_id: str):
        k = self._key(child_id, session_id)
        self._store.pop(k, None)
        self._meta.pop(k, None)

    def get_context_messages(self, child_id: str, session_id: str) -> List[Dict[str, str]]:
        """Returns messages in OpenAI-compatible format for injection into LLM context."""
        history = self.get_history(child_id, session_id)
        return [{"role": m["role"], "content": m["content"]} for m in history]


# Global singleton — lives for the lifetime of the server process
short_term_memory = ShortTermMemory()
