"""In-memory subscription router for the broker."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cortex.broker.acl import acl_allows


@dataclass
class Subscriber:
    node_id: str
    org_did: str
    topics: set[str]
    scopes: set[str]
    ws: Any = None


class Router:
    def __init__(self) -> None:
        self._by_node: dict[str, Subscriber] = {}

    def subscribe(self, sub: Subscriber) -> None:
        existing = self._by_node.get(sub.node_id)
        if existing is None:
            self._by_node[sub.node_id] = sub
        else:
            existing.topics |= sub.topics
            existing.scopes |= sub.scopes
            if sub.ws is not None:
                existing.ws = sub.ws

    def unsubscribe(self, node_id: str) -> None:
        self._by_node.pop(node_id, None)

    def all_subscribers(self) -> list[Subscriber]:
        return list(self._by_node.values())

    def subscribers_for(self, topic: str, scope: str, src_org: str) -> list[Subscriber]:
        out: list[Subscriber] = []
        for sub in self._by_node.values():
            if topic not in sub.topics:
                continue
            if scope not in sub.scopes and "*" not in sub.scopes:
                continue
            if not acl_allows(scope, src_org, sub.org_did):
                continue
            out.append(sub)
        return out
