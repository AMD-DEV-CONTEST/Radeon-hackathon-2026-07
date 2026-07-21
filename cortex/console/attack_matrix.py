from __future__ import annotations

from collections import Counter
from collections.abc import Iterable


class AttackMatrixTracker:
    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._by_technique: dict[str, list[dict]] = {}

    def on_event(self, env: dict) -> None:
        if env.get("event") != "article.published":
            return
        article = env.get("data", {}).get("article", {})
        if article.get("type") != "finding":
            return
        attack_id = article.get("payload", {}).get("attack_id")
        if not attack_id:
            return
        self._counts[attack_id] += 1
        self._by_technique.setdefault(attack_id, []).append({"id": article.get("id"), "content": article.get("content", "")})

    def absorb(self, events: Iterable[dict]) -> None:
        for e in events:
            self.on_event(e)

    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def articles_for(self, attack_id: str) -> list[dict]:
        return self._by_technique.get(attack_id, [])
