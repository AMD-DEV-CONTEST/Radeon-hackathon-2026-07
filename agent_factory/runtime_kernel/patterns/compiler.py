from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from agent_factory.runtime_kernel.bindings import BindingSet, RuntimeServices
from agent_factory.runtime_kernel.kernel.models import CompiledKernelApp
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.nodes.registry import NodeRegistry
from agent_factory.runtime_kernel.patterns.node_runner import make_wrapped_runner
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.patterns.routing import make_entry_router, make_route_router
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec, PatternNodeSpec
from agent_factory.runtime_kernel.patterns.subgraph import make_subgraph_executor, validate_subgraph_exit_routes
from agent_factory.runtime_kernel.patterns.validator import PatternValidator
from agent_factory.runtime_kernel.state import RuntimeGraphState, RuntimeState
from agent_factory.runtime_kernel.state_contracts import PackageStateManager
from agent_factory.runtime_kernel.wrappers import DEFAULT_NODE_WRAPPER_REGISTRY
from agent_factory.runtime_kernel.wrappers.system_registry import DEFAULT_SYSTEM_WRAPPER_REGISTRY
from agent_factory.runtime_render import RenderManifest, default_node_render_spec, validate_render_manifest


class PatternCompiler:
    def __init__(
        self,
        *,
        node_registry: NodeRegistry,
        pattern_registry: PatternRegistry,
        validator: PatternValidator,
    ) -> None:
        self.node_registry = node_registry
        self.pattern_registry = pattern_registry
        self.validator = validator

    def compile(
        self,
        *,
        pattern_id: str,
        bindings: BindingSet,
        services: RuntimeServices,
        render_manifest: RenderManifest,
        system_wrapper_ids: list[str] | tuple[str, ...],
        package_state_manager: PackageStateManager | None = None,
    ) -> CompiledKernelApp:
        pattern = self.pattern_registry.get(pattern_id)
        self.validator.validate(
            pattern,
            known_patterns=set(self.pattern_registry.list_pattern_ids()),
            known_node_impls=set(self.node_registry.list_impl_ids()),
        )
        validate_render_manifest(render_manifest, {node.id for node in pattern.nodes})
        system_wrappers = DEFAULT_SYSTEM_WRAPPER_REGISTRY.resolve_many(system_wrapper_ids)
        node_runners = {
            node.id: self._make_node_runner(
                node=node,
                pattern=pattern,
                bindings=bindings,
                services=services,
                render_manifest=render_manifest,
                system_wrapper_ids=system_wrapper_ids,
                system_wrappers=system_wrappers,
                package_state_manager=package_state_manager,
            )
            for node in pattern.nodes
        }
        graph = StateGraph(RuntimeGraphState)
        for node_id, runner in node_runners.items():
            graph.add_node(node_id, runner)
        graph.set_conditional_entry_point(
            make_entry_router(pattern),
            {node.id: node.id for node in pattern.nodes},
        )
        outgoing: dict[str, dict[str, str]] = {}
        for edge in pattern.edges:
            outgoing.setdefault(edge.from_, {})[edge.when] = edge.to
        for node in pattern.nodes:
            if node.id in pattern.termination.success_nodes or node.id in pattern.termination.failure_nodes:
                graph.add_edge(node.id, END)
                continue
            mapping = dict(outgoing.get(node.id, {}))
            mapping["__end__"] = END
            graph.add_conditional_edges(node.id, make_route_router(mapping), mapping)
        graph_app = graph.compile(checkpointer=services.checkpointer, store=services.memory_store)
        return CompiledKernelApp(
            pattern_spec=pattern,
            graph_app=graph_app,
            services=services,
            bindings=bindings,
            metadata={
                "compiled_pattern_id": pattern.pattern_id,
                "package_state_manager": package_state_manager,
            },
            node_runners=node_runners,
        )

    def _make_node_runner(
        self,
        *,
        node: PatternNodeSpec,
        pattern: GraphPatternSpec,
        bindings: BindingSet,
        services: RuntimeServices,
        render_manifest: RenderManifest,
        system_wrapper_ids: list[str] | tuple[str, ...],
        system_wrappers: list[Any],
        package_state_manager: PackageStateManager | None,
    ):
        node_bindings = [
            item.model_dump(mode="json")
            for item in bindings.node_bindings
            if item.target.node_id == node.id and item.target.impl == node.impl
        ]
        all_node_bindings = [item.model_dump(mode="json") for item in bindings.node_bindings]
        hook_bindings = [item.model_dump(mode="json") for item in bindings.hooks if item.enabled]
        for wrapper in node.wrappers:
            DEFAULT_NODE_WRAPPER_REGISTRY.validate_spec(wrapper)
        if node.type == "sub_graph":
            return self._make_subgraph_runner(
                node=node,
                pattern=pattern,
                binding_set=bindings,
                bindings=node_bindings,
                all_bindings=all_node_bindings,
                hook_bindings=hook_bindings,
                services=services,
                render_manifest=render_manifest,
                system_wrapper_ids=system_wrapper_ids,
                system_wrappers=system_wrappers,
                package_state_manager=package_state_manager,
            )
        impl = self.node_registry.get(node.impl)

        def execute(state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
            return impl.execute(state, context)

        return make_wrapped_runner(
            node=node,
            pattern=pattern,
            bindings=node_bindings,
            all_bindings=all_node_bindings,
            hook_bindings=hook_bindings,
            services=services,
            execute=execute,
            validate_sections=True,
            span_type="node_execution",
            node_wrappers=node.wrappers,
            node_wrapper_registry=DEFAULT_NODE_WRAPPER_REGISTRY,
            render_spec=render_manifest.nodes.get(node.id),
            system_wrappers=system_wrappers,
            package_state_manager=package_state_manager,
            writable_sections=set(getattr(impl, "writable_sections", set())),
        )

    def _make_subgraph_runner(
        self,
        *,
        node: PatternNodeSpec,
        pattern: GraphPatternSpec,
        binding_set: BindingSet,
        bindings: list[dict[str, Any]],
        all_bindings: list[dict[str, Any]],
        hook_bindings: list[dict[str, Any]],
        services: RuntimeServices,
        render_manifest: RenderManifest,
        system_wrapper_ids: list[str] | tuple[str, ...],
        system_wrappers: list[Any],
        package_state_manager: PackageStateManager | None,
    ):
        child_pattern = self.pattern_registry.get(node.pattern_ref or "")
        child = self.compile(
            pattern_id=node.pattern_ref or "",
            bindings=binding_set,
            services=services,
            render_manifest=_default_render_manifest_for_pattern(child_pattern),
            system_wrapper_ids=system_wrapper_ids,
            package_state_manager=package_state_manager,
        )
        validate_subgraph_exit_routes(node_id=node.id, pattern=pattern, child=child.pattern_spec)
        execute = make_subgraph_executor(
            node_id=node.id,
            compiled=child,
            services=services,
            input_contract=child.pattern_spec.input_contract,
            output_contract=child.pattern_spec.output_contract,
            state_mode=child.pattern_spec.state_mode,
        )
        return make_wrapped_runner(
            node=node,
            pattern=pattern,
            bindings=bindings,
            all_bindings=all_bindings,
            hook_bindings=hook_bindings,
            services=services,
            execute=execute,
            validate_sections=False,
            span_type="subgraph_execution",
            node_wrappers=node.wrappers,
            node_wrapper_registry=DEFAULT_NODE_WRAPPER_REGISTRY,
            render_spec=render_manifest.nodes.get(node.id),
            system_wrappers=system_wrappers,
            package_state_manager=package_state_manager,
            writable_sections=set(child.pattern_spec.output_contract.writable_sections),
        )


def _default_render_manifest_for_pattern(pattern: GraphPatternSpec) -> RenderManifest:
    return RenderManifest(
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
