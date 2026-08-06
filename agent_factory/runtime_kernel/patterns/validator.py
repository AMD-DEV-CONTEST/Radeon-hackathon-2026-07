from __future__ import annotations

from collections import defaultdict, deque
import re

from agent_factory.runtime_kernel.errors import PatternValidationError
from agent_factory.runtime_kernel.nodes.catalog import (
    INTERRUPT_CAPABLE_IMPLS,
    KERNEL_RESERVED_NODES,
    NODE_IMPLEMENTATION_IDS,
    NODE_TYPES,
)
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec


ALLOWED_EDGE_CONDITIONS = {
    "always",
    "model.requests_tool",
    "model.ready_to_answer",
    "intent.start_workflow",
    "intent.casual",
    "intent.wait_for_input",
    "policy.blocked",
    "tool.completed",
    "tool.failed",
    "tool.interrupted",
    "subgraph.done",
    "subgraph.need_more_input",
    "subgraph.blocked",
    "execution.finished",
}

PACKAGE_EDGE_CONDITION_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")

ALLOWED_REQUIRED_CAPABILITIES = {
    "prompt",
    "tools",
    "knowledge",
    "context",
    "observability",
    "checkpoint",
    "harness",
}


class PatternValidator:
    def validate(
        self,
        spec: GraphPatternSpec,
        *,
        known_patterns: set[str] | None = None,
        known_node_impls: set[str] | None = None,
    ) -> GraphPatternSpec:
        known_patterns = known_patterns or set()
        known_node_impls = known_node_impls or set()
        allowed_node_impls = NODE_IMPLEMENTATION_IDS.union(known_node_impls)
        if not spec.pattern_id.strip():
            raise PatternValidationError("pattern_id must not be empty.")
        if spec.version <= 0:
            raise PatternValidationError("version must be a positive integer.")
        if not spec.nodes:
            raise PatternValidationError("nodes must not be empty.")
        ids = [node.id for node in spec.nodes]
        if len(ids) != len(set(ids)):
            raise PatternValidationError("nodes[].id must be unique.")
        node_map = {node.id: node for node in spec.nodes}
        if spec.entry_node not in node_map:
            raise PatternValidationError("entry_node must reference nodes[].id.")
        for node in spec.nodes:
            if node.type not in NODE_TYPES:
                raise PatternValidationError(f"Unsupported node type: {node.type}")
            if node.type == "reserved" and node.impl not in KERNEL_RESERVED_NODES:
                raise PatternValidationError(f"Reserved node must use reserved impl: {node.impl}")
            if node.type == "sub_graph":
                if node.impl != "pattern_ref":
                    raise PatternValidationError("sub_graph nodes must use impl=pattern_ref.")
                if not node.pattern_ref:
                    raise PatternValidationError("sub_graph nodes must provide pattern_ref.")
                if known_patterns and node.pattern_ref not in known_patterns:
                    raise PatternValidationError(f"Unknown pattern_ref: {node.pattern_ref}")
            else:
                if node.impl == "pattern_ref":
                    raise PatternValidationError("Only sub_graph nodes can use impl=pattern_ref.")
                if node.impl not in allowed_node_impls:
                    raise PatternValidationError(f"Unknown node impl: {node.impl}")
        for capability in spec.constraints.required_capabilities:
            if capability not in ALLOWED_REQUIRED_CAPABILITIES:
                raise PatternValidationError(f"Unsupported required capability: {capability}")
        outgoing = defaultdict(list)
        for edge in spec.edges:
            if edge.from_ not in node_map:
                raise PatternValidationError(f"Edge from unknown node: {edge.from_}")
            if edge.to not in node_map:
                raise PatternValidationError(f"Edge to unknown node: {edge.to}")
            if not _is_allowed_edge_condition(edge.when):
                raise PatternValidationError(f"Unsupported edge condition: {edge.when}")
            outgoing[edge.from_].append(edge.to)
        for node_id in spec.interrupt_points:
            if node_id not in node_map:
                raise PatternValidationError(f"interrupt_points references unknown node: {node_id}")
            node = node_map[node_id]
            if node.type != "sub_graph" and node.impl not in INTERRUPT_CAPABLE_IMPLS:
                raise PatternValidationError(f"interrupt_points references non-interrupt-capable node: {node_id}")
        if not spec.termination.success_nodes:
            raise PatternValidationError("termination.success_nodes must not be empty.")
        for node_id in [*spec.termination.success_nodes, *spec.termination.failure_nodes]:
            if node_id not in node_map:
                raise PatternValidationError(f"termination references unknown node: {node_id}")
        if not _has_path(spec.entry_node, set(spec.termination.success_nodes), outgoing):
            raise PatternValidationError("No path from entry_node to any success node.")
        if spec.kind == "subgraph":
            if not spec.embeddable:
                raise PatternValidationError("subgraph patterns must set embeddable=true.")
            if not spec.exit_routes:
                raise PatternValidationError("subgraph patterns must define exit_routes.")
            if spec.state_mode not in {"shared", "isolated"}:
                raise PatternValidationError(f"Unsupported state_mode: {spec.state_mode}")
        return spec


def _has_path(entry: str, targets: set[str], outgoing: dict[str, list[str]]) -> bool:
    queue = deque([entry])
    seen = {entry}
    while queue:
        current = queue.popleft()
        if current in targets:
            return True
        for nxt in outgoing.get(current, []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def _is_allowed_edge_condition(condition: str) -> bool:
    if condition in ALLOWED_EDGE_CONDITIONS:
        return True
    return bool(PACKAGE_EDGE_CONDITION_RE.fullmatch(condition))
