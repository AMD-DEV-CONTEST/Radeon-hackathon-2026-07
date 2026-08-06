"""CodeRisk Agent - Memory Layer

Two-memory system using in-memory storage (ChromaDB optional):
1. Correct Memory: Store confirmed vulnerability patterns for recall
2. Error Memory: Store false-positive patterns for suppression

Makes the system "learn" over time - same code patterns get faster,
false positives get suppressed.
"""

from __future__ import annotations

import fcntl
import hashlib
import re
import json
import os
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

from core.models import Confidence, Risk, Severity

console = Console()

# Memory storage file (JSON-based, ChromaDB optional upgrade)
MEMORY_DIR = os.path.expanduser("~/.coderisk/memory")
CORRECT_MEMORY_FILE = os.path.join(MEMORY_DIR, "correct_memory.json")
ERROR_MEMORY_FILE = os.path.join(MEMORY_DIR, "error_memory.json")

# Similarity threshold for pattern matching
SIMILARITY_THRESHOLD = 0.85


class MemoryEntry:
    """A single memory entry."""

    def __init__(
        self,
        pattern_hash: str,
        cwe_id: str,
        severity: str,
        title: str,
        description: str,
        suggestion: str,
        confidence: str,
        source_count: int = 1,
        last_seen: float = 0.0,
        memory_type: str = "correct",
    ):
        self.pattern_hash = pattern_hash
        self.cwe_id = cwe_id
        self.severity = severity
        self.title = title
        self.description = description
        self.suggestion = suggestion
        self.confidence = confidence
        self.source_count = source_count
        self.last_seen = last_seen or time.time()
        self.memory_type = memory_type

    def to_dict(self) -> dict:
        return {
            "pattern_hash": self.pattern_hash,
            "cwe_id": self.cwe_id,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
            "source_count": self.source_count,
            "last_seen": self.last_seen,
            "memory_type": self.memory_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        return cls(**data)


class MemoryLayer:
    """Memory layer with correct memory and error memory."""

    def __init__(self, persist: bool = True):
        self.persist = persist
        self._correct_memory: dict[str, MemoryEntry] = {}
        self._error_memory: dict[str, MemoryEntry] = {}

        if persist:
            self._load()

    def store_correct(self, risk: Risk) -> None:
        """Store a confirmed vulnerability pattern in correct memory."""
        pattern_hash = self._hash_risk_pattern(risk)

        if pattern_hash in self._correct_memory:
            # Update existing entry
            entry = self._correct_memory[pattern_hash]
            entry.source_count += 1
            entry.last_seen = time.time()
            # Upgrade confidence if seen multiple times
            if entry.source_count >= 3 and entry.confidence != "high":
                entry.confidence = "high"
        else:
            self._correct_memory[pattern_hash] = MemoryEntry(
                pattern_hash=pattern_hash,
                cwe_id=risk.cwe_id or "",
                severity=risk.severity.value,
                title=risk.title,
                description=risk.description,
                suggestion=risk.suggestion,
                confidence=risk.confidence.value,
            )

        if self.persist:
            self._save()

    def store_error(self, risk: Risk) -> None:
        """Store a false-positive pattern in error memory."""
        pattern_hash = self._hash_risk_pattern(risk)

        if pattern_hash in self._error_memory:
            entry = self._error_memory[pattern_hash]
            entry.source_count += 1
            entry.last_seen = time.time()
        else:
            self._error_memory[pattern_hash] = MemoryEntry(
                pattern_hash=pattern_hash,
                cwe_id=risk.cwe_id or "",
                severity=risk.severity.value,
                title=risk.title,
                description=risk.description,
                suggestion=risk.suggestion,
                confidence="low",
                memory_type="error",
            )

        if self.persist:
            self._save()

    def recall(self, risk: Risk) -> Optional[tuple[MemoryEntry, str]]:
        """Check if a risk pattern matches known correct/incorrect patterns.

        Returns:
            (MemoryEntry, memory_type) if found, None otherwise.
            memory_type is "error" or "correct".
        """
        pattern_hash = self._hash_risk_pattern(risk)

        # Check error memory first (suppress known false positives)
        if pattern_hash in self._error_memory:
            entry = self._error_memory[pattern_hash]
            if entry.source_count >= 2:
                console.print(
                    f"[dim]  Memory: suppressed known false positive {risk.id} "
                    f"(seen {entry.source_count} times)[/]"
                )
                return (entry, "error")

        # Check correct memory (boost confidence for known patterns)
        if pattern_hash in self._correct_memory:
            entry = self._correct_memory[pattern_hash]
            console.print(
                f"[dim]  Memory: recalled pattern for {risk.id} "
                f"(seen {entry.source_count} times)[/]"
            )
            return (entry, "correct")

        return None

    def get_stats(self) -> dict:
        """Get memory statistics."""
        return {
            "correct_patterns": len(self._correct_memory),
            "error_patterns": len(self._error_memory),
            "total": len(self._correct_memory) + len(self._error_memory),
        }

    def _hash_risk_pattern(self, risk: Risk) -> str:
        """Create a normalized hash of the risk pattern for matching.

        Normalizes variable names to <VAR> and strings to <STR>
        so that similar patterns with different variable names match.
        """
        code_pattern = ""
        if risk.evidence:
            code_pattern = risk.evidence[0].snippet[:100]

        # Normalize: replace variable names with <VAR>, preserve keywords
        _KEYWORDS = {'if', 'for', 'while', 'return', 'int', 'char', 'void',
                     'def', 'class', 'import', 'from', 'in', 'is', 'not',
                     'and', 'or', 'True', 'False', 'None', 'NULL', 'sizeof',
                     'struct', 'else', 'elif', 'try', 'except', 'with', 'as'}
        def _replace(match):
            word = match.group(0)
            return '<VAR>' if word not in _KEYWORDS and not word.isdigit() else word
        normalized = re.sub(r'\b[a-zA-Z_]\w*\b', _replace, code_pattern)
        # Normalize: replace string literals with <STR>
        normalized = re.sub(r'"[^"]*"', '<STR>', normalized)
        normalized = re.sub(r"'[^']*'", '<STR>', normalized)

        key = f"{risk.cwe_id}:{risk.language}:{normalized}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _save(self):
        """Persist memory to disk with proper fd-level locking."""
        os.makedirs(MEMORY_DIR, exist_ok=True)

        correct_data = {k: v.to_dict() for k, v in self._correct_memory.items()}
        error_data = {k: v.to_dict() for k, v in self._error_memory.items()}

        for path, data in [(CORRECT_MEMORY_FILE, correct_data),
                           (ERROR_MEMORY_FILE, error_data)]:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.write(fd, json.dumps(data, indent=2).encode())
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _load(self):
        """Load memory from disk."""
        try:
            if os.path.exists(CORRECT_MEMORY_FILE):
                with open(CORRECT_MEMORY_FILE) as f:
                    data = json.load(f)
                self._correct_memory = {
                    k: MemoryEntry.from_dict(v) for k, v in data.items()
                }
        except Exception:
            pass

        try:
            if os.path.exists(ERROR_MEMORY_FILE):
                with open(ERROR_MEMORY_FILE) as f:
                    data = json.load(f)
                self._error_memory = {
                    k: MemoryEntry.from_dict(v) for k, v in data.items()
                }
        except Exception:
            pass

    def clear(self):
        """Clear all memory."""
        self._correct_memory.clear()
        self._error_memory.clear()
        if self.persist:
            self._save()
