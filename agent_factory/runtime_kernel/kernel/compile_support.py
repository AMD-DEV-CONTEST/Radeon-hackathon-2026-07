from __future__ import annotations

from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_render import RenderManifest, default_node_render_spec, validate_render_manifest


def required_services_for_pattern(pattern: GraphPatternSpec) -> list[str]:
    required = {"observability_manager", "checkpointer"}
    for node in pattern.nodes:
        if node.impl.startswith("cognitive."):
            required.update({"model_operation_service", "context_engine", "context_system"})
        elif node.impl.startswith("operational.tool_call"):
            required.add("tool_registry")
        for wrapper in node.wrappers:
            if wrapper.id.startswith("context."):
                required.add("context_engine")
            elif wrapper.id.startswith("tool."):
                required.add("tool_registry")
    for capability in pattern.constraints.required_capabilities:
        if capability == "tools":
            required.add("tool_registry")
        elif capability == "knowledge":
            required.add("knowledge_runtime")
        elif capability == "context":
            required.add("context_engine")
        elif capability == "harness":
            required.add("harness_bridge")
    return sorted(required)


def ensure_memory_runtime(services: RuntimeServices) -> None:
    if services.memory_system is None:
        return
    runtime = services.memory_system
    config = getattr(runtime, "config", None)
    if config is None or not getattr(config, "enabled", False):
        return
    if getattr(runtime, "store", None) is None:
        if services.memory_store is None:
            raise RuntimeError("cross-session memory is enabled but BaseStore is missing")
        runtime.store = services.memory_store


def resolve_render_manifest(pattern: GraphPatternSpec, render_manifest: RenderManifest | dict | None) -> RenderManifest:
    if render_manifest is None:
        manifest = RenderManifest(
            graph_id=pattern.pattern_id,
            nodes={
                node.id: default_node_render_spec(
                    node_id=node.id,
                    node_type=node.type,
                    impl=node.impl,
                    pattern_id=pattern.pattern_id,
                )
                for node in pattern.nodes
            },
        )
    elif isinstance(render_manifest, RenderManifest):
        manifest = render_manifest
    else:
        manifest = RenderManifest.model_validate(render_manifest)
    return validate_render_manifest(manifest, {node.id for node in pattern.nodes})
