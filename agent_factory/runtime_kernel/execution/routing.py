from __future__ import annotations

from dataclasses import dataclass

from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_kernel.state import RuntimeState


@dataclass(frozen=True)
class RouteResolution:
    condition: str | None
    next_node: str | None


def resolve_route(spec: GraphPatternSpec, *, current_node: str, state: RuntimeState) -> RouteResolution:
    fallback = None
    explicit: dict[str, str] = {}
    for edge in spec.edges:
        if edge.from_ != current_node:
            continue
        if edge.when == "always":
            fallback = edge.to
        else:
            explicit[edge.when] = edge.to
    decision = state.execution.route_decision
    if decision and decision in explicit:
        return RouteResolution(condition=decision, next_node=explicit[decision])
    if fallback is not None:
        return RouteResolution(condition="always", next_node=fallback)
    return RouteResolution(condition=None, next_node=None)


def resolve_next_node(spec: GraphPatternSpec, *, current_node: str, state: RuntimeState) -> str | None:
    return resolve_route(spec, current_node=current_node, state=state).next_node
