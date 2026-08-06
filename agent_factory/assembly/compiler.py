from __future__ import annotations

from dataclasses import dataclass

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.assembly.validator import AgentAssemblyValidator
from agent_factory.runtime_contracts.contribution import RuntimeBuildResult
from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.kernel import CompiledKernelApp, RuntimeKernelFacade
from agent_factory.runtime_kernel.kernel.compile_support import resolve_render_manifest
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_render import RenderManifest


@dataclass(slots=True)
class CompiledAgentAssembly:
    spec: AgentAssemblySpec
    pattern_spec: GraphPatternSpec
    compiled_app: CompiledKernelApp
    runtime_build: RuntimeBuildResult | None = None

    @property
    def runtime_config(self) -> dict:
        agent_config = dict(self.spec.runtime.agent_config)
        agent_config["agent_id"] = self.spec.agent.id
        return {
            "user_config": dict(self.spec.runtime.user_config),
            "agent_config": agent_config,
            "session_config": dict(self.runtime_build.session_config if self.runtime_build else {}),
        }


class AgentAssemblyCompiler:
    def __init__(self, *, facade: RuntimeKernelFacade | None = None) -> None:
        self.facade = facade or RuntimeKernelFacade()
        self.validator = AgentAssemblyValidator(pattern_registry=self.facade.instance.pattern_registry)

    def compile(
        self,
        spec: AgentAssemblySpec,
        *,
        runtime_build: RuntimeBuildResult | None = None,
        services: RuntimeServices | None = None,
        render_manifest: RenderManifest | None = None,
        system_wrapper_ids: list[str] | tuple[str, ...] | None = None,
    ) -> CompiledAgentAssembly:
        if runtime_build and runtime_build.node_providers:
            self.facade.register_node_providers(runtime_build.node_providers)
        self.validator.validate(spec)
        assembled_pattern = self._assemble_pattern(spec)
        resolved_render_manifest = self._render_manifest_for_compile(
            assembled_pattern,
            render_manifest=render_manifest,
        )
        self.facade.instance.pattern_registry.register(assembled_pattern)
        resolved_services = runtime_build.services if runtime_build else services
        compiled_app = self.facade.compile(
            pattern_id=assembled_pattern.pattern_id,
            bindings=spec.bindings,
            services=resolved_services,
            render_manifest=resolved_render_manifest,
            system_wrapper_ids=runtime_build.system_wrappers if runtime_build else system_wrapper_ids,
            node_providers=runtime_build.node_providers if runtime_build else None,
        )
        compiled_app.metadata["agent_id"] = spec.agent.id
        return CompiledAgentAssembly(
            spec=spec,
            pattern_spec=assembled_pattern,
            compiled_app=compiled_app,
            runtime_build=runtime_build,
        )

    def run(
        self,
        compiled: CompiledAgentAssembly,
        *,
        user_input: str,
        services: RuntimeServices | None = None,
    ):
        if services is not None and services is not compiled.compiled_app.services:
            compiled = self.compile(
                compiled.spec,
                services=services,
                system_wrapper_ids=compiled.runtime_build.system_wrappers if compiled.runtime_build else None,
            )
        return self.facade.run(
            compiled.compiled_app,
            user_input=user_input,
            **compiled.runtime_config,
        )

    def _assemble_pattern(self, spec: AgentAssemblySpec) -> GraphPatternSpec:
        base_pattern = self.facade.instance.pattern_registry.get(spec.runtime.pattern_id)
        assembled = base_pattern.model_copy(deep=True)
        assembled.pattern_id = spec.runtime.compiled_pattern_id or f"{spec.agent.id}__{spec.runtime.pattern_id}"
        assembled.name = f"{spec.agent.id} assembly"
        node_map = {node.id: node for node in assembled.nodes}
        for override in spec.graph_overrides.node_wrappers:
            node = node_map[override.node_id]
            if override.replace_existing:
                node.wrappers = list(override.wrappers)
            else:
                node.wrappers = [*node.wrappers, *override.wrappers]
        return assembled

    def _render_manifest_for_compile(
        self,
        pattern: GraphPatternSpec,
        *,
        render_manifest: RenderManifest | None,
    ) -> RenderManifest:
        return resolve_render_manifest(pattern, render_manifest)
