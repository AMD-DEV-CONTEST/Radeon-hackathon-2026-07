from __future__ import annotations

import inspect
from pathlib import Path
from typing import Callable, Mapping

from agent_factory.tooling.entrypoints import (
    EntrypointAdapterError,
    EntrypointAdapterRegistry,
    MCPEntrypointAdapter,
    MCPToolClient,
    PythonEntrypointAdapter,
    ToolEntrypointCallable,
)
from agent_factory.tooling.risk import ToolRiskEvaluator


class ToolEntrypointError(EntrypointAdapterError):
    pass


class ToolEntrypointLoader:
    """Facade over the protocol-based entrypoint adapter registry."""

    def __init__(
        self,
        *,
        package_root: str | Path | None = None,
        allowed_python_roots: list[str | Path] | None = None,
        adapter_registry: EntrypointAdapterRegistry | None = None,
        mcp_clients: Mapping[str, MCPToolClient] | None = None,
    ) -> None:
        if adapter_registry is not None:
            self.registry = adapter_registry
        else:
            self.registry = EntrypointAdapterRegistry(
                [
                    MCPEntrypointAdapter(clients=mcp_clients),
                    PythonEntrypointAdapter(package_root=package_root, allowed_roots=allowed_python_roots),
                ]
            )

    def load(self, entrypoint: str) -> ToolEntrypointCallable:
        try:
            function = self.registry.load(entrypoint)
            return _validate_function(
                function,
                entrypoint,
                parameter_names=("arguments", "resources"),
                label="tool entrypoint",
            )
        except EntrypointAdapterError as exc:
            raise ToolEntrypointError(str(exc)) from exc

    def load_risk_evaluator(self, entrypoint: str) -> ToolRiskEvaluator:
        try:
            function = self.registry.load(entrypoint)
            return _validate_function(
                function,
                entrypoint,
                parameter_names=("arguments", "context"),
                label="tool risk evaluator",
            )
        except EntrypointAdapterError as exc:
            raise ToolEntrypointError(str(exc)) from exc


def _validate_function(
    function: Callable,
    entrypoint: str,
    *,
    parameter_names: tuple[str, str],
    label: str,
):
    if inspect.iscoroutinefunction(function):
        raise EntrypointAdapterError(f"{label} cannot be async: {entrypoint}")
    signature = inspect.signature(function)
    positional = [
        parameter.name
        for parameter in signature.parameters.values()
        if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    if tuple(positional[:2]) != parameter_names:
        expected = " and ".join(parameter_names)
        raise EntrypointAdapterError(f"{label} must accept {expected} parameters")
    return function
