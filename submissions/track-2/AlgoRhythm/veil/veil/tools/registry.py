"""Tool registry.

Tools are plain Python functions with a JSON-schema description. The registry
exists so that a persona's tool allowlist is enforced at dispatch time, not by
hoping the model reads its instructions: `Registry.for_persona(...)` returns a
view that physically cannot call anything outside the allowlist.

Every dispatch is recorded, because "which tool produced this evidence" is the
question a Tier M finding has to answer.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from veil.types import now_ms


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]

    def as_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolCallRecord:
    tool: str
    args: dict[str, Any]
    result_summary: str
    persona: str
    ts_ms: int = field(default_factory=now_ms)
    error: str | None = None


class ToolBudgetExceeded(RuntimeError):
    pass


class ToolNotPermitted(RuntimeError):
    pass


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self.calls: list[ToolCallRecord] = []

    def register(
        self, name: str, description: str, parameters: dict[str, Any]
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[name] = ToolSpec(name, description, parameters, fn)
            return fn

        return deco

    def schemas_for(self, allowed: tuple[str, ...]) -> list[dict[str, Any]]:
        return [
            self._tools[n].as_openai_schema() for n in allowed if n in self._tools
        ]

    def for_persona(self, persona: str, allowed: tuple[str, ...], budget: int) -> "PersonaTools":
        return PersonaTools(self, persona, allowed, budget)

    async def _dispatch(self, name: str, args: dict[str, Any]) -> Any:
        spec = self._tools[name]
        if inspect.iscoroutinefunction(spec.fn):
            return await spec.fn(**args)
        return spec.fn(**args)


class PersonaTools:
    """A persona-scoped view of the registry. The allowlist is enforced here."""

    def __init__(self, registry: Registry, persona: str, allowed: tuple[str, ...], budget: int):
        self.registry = registry
        self.persona = persona
        self.allowed = set(allowed)
        self.budget = budget
        self.used = 0

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return self.registry.schemas_for(tuple(self.allowed))

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        if name not in self.allowed:
            raise ToolNotPermitted(
                f"{self.persona} may not call {name!r}; permitted: {sorted(self.allowed)}"
            )
        if self.used >= self.budget:
            raise ToolBudgetExceeded(
                f"{self.persona} exhausted its budget of {self.budget} tool calls"
            )
        self.used += 1
        try:
            result = await self.registry._dispatch(name, args)
        except Exception as exc:  # noqa: BLE001 - surfaced to the model, not swallowed
            self.registry.calls.append(
                ToolCallRecord(name, args, "", self.persona, error=str(exc))
            )
            raise
        summary = json.dumps(result, default=str)[:400]
        self.registry.calls.append(ToolCallRecord(name, args, summary, self.persona))
        return result


REGISTRY = Registry()
