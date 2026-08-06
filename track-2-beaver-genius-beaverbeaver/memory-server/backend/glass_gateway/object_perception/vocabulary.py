from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VocabularySnapshot:
    vocabulary_id: str
    prompts: tuple[str, ...]
    sources: dict[str, str]
    hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "vocabulary_id": self.vocabulary_id,
            "prompts": list(self.prompts),
            "sources": dict(self.sources),
            "hash": self.hash,
        }


class VocabularyComposer:
    def __init__(self, global_path: str | Path, *, review_store, max_classes: int = 120) -> None:
        self.global_path = Path(global_path)
        self.review_store = review_store
        self.max_classes = max(1, min(120, int(max_classes)))

    def compose(self) -> VocabularySnapshot:
        payload = json.loads(self.global_path.read_text(encoding="utf-8"))
        objects = [item for item in payload.get("objects") or [] if isinstance(item, dict)]
        confirmed = self.review_store.confirmed_object_prompts()
        recent = self.review_store.recent_stable_object_labels(limit=80)
        ordered: list[tuple[str, str]] = []
        ordered.extend(
            (str(item.get("prompt") or item.get("label") or ""), "user_confirmed")
            for item in confirmed
            if isinstance(item, dict)
        )
        ordered.extend(
            (str(item.get("prompt") or item.get("label") or ""), "global_memory_critical")
            for item in objects
            if item.get("default_tier") == "memory_critical"
        )
        ordered.extend((str(item), "recent_stable") for item in recent)
        ordered.extend(
            (str(item.get("prompt") or item.get("label") or ""), "global_context")
            for item in objects
            if item.get("default_tier") != "memory_critical"
        )
        prompts: list[str] = []
        sources: dict[str, str] = {}
        seen: set[str] = set()
        for raw_prompt, source in ordered:
            prompt = raw_prompt.strip()
            key = prompt.casefold()
            if not prompt or key in seen:
                continue
            seen.add(key)
            prompts.append(prompt)
            sources[prompt] = source
            if len(prompts) >= self.max_classes:
                break
        canonical = json.dumps(prompts, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return VocabularySnapshot(
            vocabulary_id=str(payload.get("vocabulary_id") or "portable-memory-objects-v2"),
            prompts=tuple(prompts),
            sources=sources,
            hash=digest,
        )
