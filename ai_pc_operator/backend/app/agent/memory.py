"""Memory module - short-term and long-term memory."""

from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
MEMORY_DIR = ROOT / "ai_pc_operator" / "data" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)


class Memory:
    """Agent memory system."""

    def __init__(self, max_short_term: int = 50):
        """Initialize memory."""
        self.max_short_term = max_short_term
        self.short_term: List[Dict[str, Any]] = []
        self.long_term_path = MEMORY_DIR / "long_term.jsonl"

    async def add(
        self,
        command: str,
        intent: str,
        response: Dict[str, Any],
    ) -> None:
        """Add entry to memory."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "command": command,
            "intent": intent,
            "response": response,
        }

        # Add to short-term
        self.short_term.append(entry)

        # Trim if too long
        if len(self.short_term) > self.max_short_term:
            # Move oldest to long-term
            old = self.short_term.pop(0)
            await self._save_long_term(old)

    async def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent memory entries."""
        return self.short_term[-limit:]

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Search memory for similar commands."""
        query_lower = query.lower()
        results = []

        # Search short-term
        for entry in self.short_term:
            if query_lower in entry["command"].lower():
                results.append(entry)

        results.extend(await asyncio.to_thread(self._search_long_term_sync, query_lower))

        return results

    async def _save_long_term(self, entry: Dict[str, Any]) -> None:
        """Save entry to long-term memory."""
        await asyncio.to_thread(self._save_long_term_sync, entry)

    async def clear(self) -> None:
        """Clear all memory."""
        self.short_term.clear()
        await asyncio.to_thread(self._clear_long_term_sync)

    def _search_long_term_sync(self, query_lower: str) -> List[Dict[str, Any]]:
        """Blocking JSONL search used through asyncio.to_thread."""
        if not self.long_term_path.exists():
            return []

        matches = []
        with open(self.long_term_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if query_lower in entry.get("command", "").lower():
                    matches.append(entry)
        return matches

    def _save_long_term_sync(self, entry: Dict[str, Any]) -> None:
        """Blocking JSONL append used through asyncio.to_thread."""
        with open(self.long_term_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _clear_long_term_sync(self) -> None:
        """Blocking long-term delete used through asyncio.to_thread."""
        if self.long_term_path.exists():
            self.long_term_path.unlink()
