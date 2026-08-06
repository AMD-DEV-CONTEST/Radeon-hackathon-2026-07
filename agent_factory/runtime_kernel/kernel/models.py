from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_factory.runtime_kernel.bindings import BindingSet, RuntimeServices
from agent_factory.runtime_kernel.nodes.registry import NodeRegistry
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_kernel.patterns.validator import PatternValidator


@dataclass
class RuntimeKernelInstance:
    services: RuntimeServices
    node_registry: NodeRegistry
    pattern_registry: PatternRegistry
    validator: PatternValidator
    compiler: Any
    controller: Any


@dataclass
class CompiledKernelApp:
    pattern_spec: GraphPatternSpec
    graph_app: Any
    services: RuntimeServices
    bindings: BindingSet
    metadata: dict[str, Any] = field(default_factory=dict)
    node_runners: dict[str, Any] = field(default_factory=dict)
