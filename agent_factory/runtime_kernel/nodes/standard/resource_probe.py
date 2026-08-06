from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class OperationalResourceProbeNode:
    impl_id = "operational.resource_probe"
    node_type = "operational"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"context", "execution"}

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        binding_payload = _first_binding_payload(context.bindings) or {}
        targets = [str(item) for item in binding_payload.get("paths", [])]
        results = []
        for item in targets:
            path = Path(item)
            results.append(
                {
                    "path": item,
                    "exists": path.exists(),
                    "is_file": path.is_file(),
                    "is_dir": path.is_dir(),
                }
            )
        return {
            "context": {
                "hidden_context": {
                    "resource_probe": {
                        "probed_resources": results,
                    }
                },
                "tool_context": {
                    "probed_resources": results,
                },
            },
            "execution": {"current_node": context.node_id, "route_decision": "always"},
        }


def _first_binding_payload(bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bindings:
        return None
    return dict(bindings[0].get("payload") or {})
