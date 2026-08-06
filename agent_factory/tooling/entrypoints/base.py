from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


ToolEntrypointCallable = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


class EntrypointAdapter(Protocol):
    protocol: str

    def can_load(self, entrypoint: str) -> bool:
        ...

    def load(self, entrypoint: str) -> ToolEntrypointCallable:
        ...


@dataclass(frozen=True, slots=True)
class ParsedEntrypoint:
    protocol: str
    target: str


class EntrypointAdapterError(ValueError):
    pass


class EntrypointAdapterRegistry:
    def __init__(self, adapters: list[EntrypointAdapter] | None = None) -> None:
        self._adapters = list(adapters or [])

    def register(self, adapter: EntrypointAdapter) -> None:
        self._adapters.append(adapter)

    def load(self, entrypoint: str) -> ToolEntrypointCallable:
        errors: list[str] = []
        for adapter in self._adapters:
            if not adapter.can_load(entrypoint):
                continue
            try:
                return adapter.load(entrypoint)
            except Exception as exc:
                errors.append(f"{adapter.protocol}: {exc}")
        if errors:
            raise EntrypointAdapterError("; ".join(errors))
        raise EntrypointAdapterError(f"unsupported tool entrypoint: {entrypoint}")


def parse_protocol(entrypoint: str) -> ParsedEntrypoint:
    if ":" not in entrypoint:
        raise EntrypointAdapterError("entrypoint must contain a protocol or function separator")
    protocol, target = entrypoint.split(":", 1)
    protocol = protocol.strip()
    target = target.strip()
    if protocol in {"python", "python-import", "mcp"}:
        if not target:
            raise EntrypointAdapterError("entrypoint target must be non-empty")
        return ParsedEntrypoint(protocol=protocol, target=target)
    return ParsedEntrypoint(protocol="python-import", target=entrypoint.strip())
