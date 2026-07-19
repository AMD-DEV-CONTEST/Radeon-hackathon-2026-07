"""Hermes-style long-term memory: two Markdown files (`memory/user.md` for
identity/preference, `memory/memory.md` for everything else -- facts,
contacts, projects, goals) instead of a JSON blob or a vector DB.

Same public method surface as `core.utils.memory.MemoryManager` on purpose
(`load_all`, `load`, `save`, `add_entry`, `find_duplicates`, `claim_ownerless`,
`increment_uses`) so `core/memory/memory_extractor.py`'s extraction/dedup/
audit logic (LLM calls, Jaccard fallback, the "never remove >50% in one
pass" safety net) works by pointing it at this class instead of rewriting
that logic for Markdown.

Design constraints this exists to satisfy (see the Aetheris revival plan):
- Restriction #2 (single source of truth): these two files ARE the store,
  no JSON/vector copy anywhere else to go stale against them.
- Restriction #16 (no free-text rewrite of the whole file): the LLM's role
  is bounded to producing short fact strings (via memory_extractor.py);
  THIS module is what deterministically renders those into file bytes --
  the model never writes raw Markdown to disk. `save()` re-parses what it's
  about to write and checks the entry count round-trips before committing,
  so a rendering bug fails loudly instead of silently corrupting the file.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Dict, List, Optional

from core.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)

# identity/preference are about the USER (user.md); everything else is
# world/project knowledge (memory.md). Matches memory_extractor.py's
# existing category vocabulary (EXTRACT_SYSTEM_PROMPT).
USER_CATEGORIES = {"identity", "preference"}

_ENTRY_RE = re.compile(r"^- (?P<text>.+?)\s*<!--\s*(?P<meta>.+?)\s*-->\s*$")
_HEADERS = {
    "user": "# User\n\nWhat Aetheris knows about you: identity and preferences.\n\n",
    "memory": "# Memory\n\nWorld and project facts Aetheris has learned.\n\n",
}


def _escape(text: str) -> str:
    # A literal "-->" or "<!--" in the fact text would break the metadata
    # suffix's own delimiters; short factual sentences never legitimately
    # need either, so strip rather than try to escape-and-unescape them.
    return text.replace("<!--", "").replace("-->", "").strip()


def _render_entry(entry: Dict) -> str:
    text = _escape(entry.get("text", ""))
    meta_fields = ["id", "category", "source", "owner", "uses", "pinned", "timestamp", "session_id"]
    meta = " ".join(
        f"{k}={entry[k]}" for k in meta_fields
        if entry.get(k) is not None and entry.get(k) != ""
    )
    return f"- {text} <!-- {meta} -->"


def _parse_entry(line: str) -> Optional[Dict]:
    m = _ENTRY_RE.match(line)
    if not m:
        return None
    entry: Dict = {"text": m.group("text")}
    for pair in m.group("meta").split():
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        if k == "uses":
            try:
                v = int(v)
            except ValueError:
                v = 0
        elif k == "timestamp":
            try:
                v = int(v)
            except ValueError:
                v = int(time.time())
        elif k == "pinned":
            v = v.lower() == "true"
        entry[k] = v
    entry.setdefault("id", str(uuid.uuid4()))
    entry.setdefault("category", "fact")
    entry.setdefault("source", "unknown")
    entry.setdefault("uses", 0)
    entry.setdefault("timestamp", int(time.time()))
    return entry


def _parse_file(path: str) -> List[Dict]:
    if not os.path.isfile(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.startswith("- "):
                continue
            entry = _parse_entry(line)
            if entry:
                entries.append(entry)
    return entries


def _render_file(entries: List[Dict], header: str) -> str:
    lines = [_render_entry(e) for e in entries]
    return header + "\n".join(lines) + ("\n" if lines else "")


class MarkdownMemoryManager:
    """Drop-in (same method surface) replacement for
    `core.utils.memory.MemoryManager`, backed by `memory/user.md` +
    `memory/memory.md` instead of `data/memory.json`."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.memory_dir = os.path.join(data_dir, "memory")
        self.user_file = os.path.join(self.memory_dir, "user.md")
        self.memory_file = os.path.join(self.memory_dir, "memory.md")
        os.makedirs(self.memory_dir, exist_ok=True)
        self.ensure_file_exists()

    def _file_for(self, category: str) -> str:
        return self.user_file if category in USER_CATEGORIES else self.memory_file

    def ensure_file_exists(self):
        for kind, path in (("user", self.user_file), ("memory", self.memory_file)):
            if not os.path.exists(path):
                atomic_write_text(path, _HEADERS[kind])

    def load_all(self) -> List[Dict]:
        return _parse_file(self.user_file) + _parse_file(self.memory_file)

    def load(self, owner: str = None) -> List[Dict]:
        entries = self.load_all()
        if owner is None:
            return entries
        return [e for e in entries if e.get("owner") == owner]

    def claim_ownerless(self, owner: str):
        entries = self.load_all()
        changed = False
        claimed = 0
        for entry in entries:
            if not entry.get("owner"):
                entry["owner"] = owner
                changed = True
                claimed += 1
        if changed:
            self.save(entries)
            logger.info("Claimed %d ownerless memories for %s", claimed, owner)

    def save(self, entries: List[Dict]):
        """Deterministically re-render both files from `entries`. The LLM
        never produces these bytes directly -- it only produces the `text`/
        `category` fields upstream (memory_extractor.py); this function is
        the only thing that turns a validated list into file content, and
        it verifies its own output round-trips before committing (Restriction
        #16)."""
        for entry in entries:
            entry.setdefault("id", str(uuid.uuid4()))
            entry.setdefault("timestamp", int(time.time()))
            entry.setdefault("source", "user")
            entry.setdefault("category", "fact")

        user_entries = [e for e in entries if e.get("category") in USER_CATEGORIES]
        memory_entries = [e for e in entries if e.get("category") not in USER_CATEGORIES]

        user_content = _render_file(user_entries, _HEADERS["user"])
        memory_content = _render_file(memory_entries, _HEADERS["memory"])

        # Validate: re-parse what we're about to write and confirm the
        # entry count matches. A rendering bug (e.g. a fact text containing
        # something that breaks the line format) fails loudly here instead
        # of silently writing a file the parser can't read back.
        if len(_parse_file_from_text(user_content)) != len(user_entries):
            raise RuntimeError("user.md render/parse round-trip mismatch -- refusing to write")
        if len(_parse_file_from_text(memory_content)) != len(memory_entries):
            raise RuntimeError("memory.md render/parse round-trip mismatch -- refusing to write")

        atomic_write_text(self.user_file, user_content)
        atomic_write_text(self.memory_file, memory_content)

    def add_entry(self, text: str, source: str = "user", category: str = "fact", owner: str = None) -> Dict:
        if not text.strip():
            raise ValueError("Memory text cannot be empty")
        entry = {
            "id": str(uuid.uuid4()),
            "text": text.strip(),
            "timestamp": int(time.time()),
            "source": source,
            "category": category,
            "uses": 0,
        }
        if owner:
            entry["owner"] = owner
        return entry

    def increment_uses(self, ids: List[str]) -> None:
        if not ids:
            return
        id_set = set(ids)
        entries = self.load_all()
        changed = False
        for e in entries:
            if e.get("id") in id_set:
                e["uses"] = int(e.get("uses", 0) or 0) + 1
                changed = True
        if changed:
            self.save(entries)

    def delete_entries(self, ids: List[str]) -> int:
        """Removes entries by id. Returns how many were actually removed."""
        if not ids:
            return 0
        id_set = set(ids)
        entries = self.load_all()
        remaining = [e for e in entries if e.get("id") not in id_set]
        removed = len(entries) - len(remaining)
        if removed:
            self.save(remaining)
        return removed

    def find_duplicates(self, text: str, entries: List[Dict] = None) -> List[Dict]:
        if entries is None:
            entries = self.load()
        text_lower = text.strip().lower()
        return [entry for entry in entries if entry["text"].lower() == text_lower]

    def get_relevant_memories(self, query: str, memories: list, threshold: float = 0.05, max_items: int = 8):
        from core.utils.memory import get_text_similarity
        scored = []
        for m in memories:
            score = get_text_similarity(query, m.get("text", ""))
            if score >= threshold:
                scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:max_items]]


def _parse_file_from_text(content: str) -> List[Dict]:
    entries = []
    for line in content.split("\n"):
        if not line.startswith("- "):
            continue
        entry = _parse_entry(line)
        if entry:
            entries.append(entry)
    return entries
