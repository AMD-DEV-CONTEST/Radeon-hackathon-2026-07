from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class Tenant:
    org_did: str
    slug: str


def load_tenants(registry_path: Path) -> list[dict]:
    if not registry_path.exists():
        return []
    data = json.loads(registry_path.read_text())
    return data.get("tenants", [])


class NodeRegistry:
    """Tracks the debug HTTP base URL for each connected node."""

    def __init__(self) -> None:
        self._nodes: dict[str, tuple[str, httpx.BaseClient | None]] = {}

    def register(self, slug: str, base_url: str, transport: httpx.BaseTransport | None = None) -> None:
        client = httpx.AsyncClient(base_url=base_url, transport=transport)
        self._nodes[slug] = (base_url, client)

    def get(self, slug: str) -> tuple[str, httpx.AsyncClient | None]:
        return self._nodes.get(slug, ("", None))

    @property
    def known(self) -> list[str]:
        return list(self._nodes.keys())
