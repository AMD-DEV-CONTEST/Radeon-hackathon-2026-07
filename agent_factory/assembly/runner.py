from __future__ import annotations

from pathlib import Path

from agent_factory.assembly.compiler import AgentAssemblyCompiler, CompiledAgentAssembly
from agent_factory.assembly.loader import AgentAssemblyLoader
from agent_factory.assembly.schema import AgentAssemblySpec, AssemblyRunReport
from agent_factory.runtime_contracts.builder import RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_contracts.loader import AgentPackageLoader
from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.harness import FixtureBundle, HarnessBridge


class AgentAssemblyRunner:
    def __init__(self, *, compiler: AgentAssemblyCompiler | None = None) -> None:
        self.compiler = compiler or AgentAssemblyCompiler()
        self.loader = AgentAssemblyLoader()
        self.package_loader = AgentPackageLoader()

    def run_path(
        self,
        path: str | Path,
        *,
        services: RuntimeServices | None = None,
        fixture: FixtureBundle | None = None,
    ) -> AssemblyRunReport:
        if Path(path).name == "agent_package.json":
            package = self.package_loader.load_path(path)
            runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=services or self.compiler.facade.instance.services,
            )
            compiled = self.compiler.compile(package.assembly_spec, runtime_build=runtime_build)
            return self.run_compiled(compiled, fixture=fixture)
        return self.run_spec(
            self.loader.load_path(path),
            services=services,
            fixture=fixture,
        )

    def run_spec(
        self,
        spec: AgentAssemblySpec,
        *,
        services: RuntimeServices | None = None,
        fixture: FixtureBundle | None = None,
    ) -> AssemblyRunReport:
        compiled = self.compiler.compile(spec, services=services)
        return self.run_compiled(compiled, fixture=fixture)

    def run_compiled(
        self,
        compiled: CompiledAgentAssembly,
        *,
        fixture: FixtureBundle | None = None,
    ) -> AssemblyRunReport:
        fixture = fixture or FixtureBundle()
        scenario_results = []
        errors = []
        bridge = HarnessBridge(facade=self.compiler.facade)
        for scenario in compiled.spec.harness:
            result = bridge.run_scenario(
                pattern_id=compiled.pattern_spec.pattern_id,
                bindings=compiled.spec.bindings,
                services=compiled.compiled_app.services,
                fixture=fixture,
                scenario=scenario,
            )
            dumped = result.model_dump(mode="json")
            scenario_results.append(dumped)
            if result.error:
                errors.append(result.error)
        status = "passed" if not errors and all(item["status"] == "passed" for item in scenario_results) else "failed"
        return AssemblyRunReport(
            assembly_id=compiled.spec.metadata.get("assembly_id", compiled.spec.agent.id),
            agent_id=compiled.spec.agent.id,
            status=status,
            scenario_results=scenario_results,
            errors=errors,
        )

    def run_invocation(
        self,
        compiled: CompiledAgentAssembly,
        *,
        user_input: str,
        user_config: dict | None = None,
        agent_config: dict | None = None,
        session_config: dict | None = None,
    ) -> AssemblyRunReport:
        state = self.compiler.facade.run(
            compiled.compiled_app,
            user_input=user_input,
            user_config={**compiled.spec.runtime.user_config, **(user_config or {})},
            agent_config={**compiled.spec.runtime.agent_config, **(agent_config or {})},
            session_config={**compiled.runtime_config["session_config"], **(session_config or {})},
        )
        result = {
            "scenario_id": "runtime_invocation",
            "status": "passed" if state.execution.finish_status == "completed" else "failed",
            "error": _error_from_state(state),
            "assertion_results": [],
            "final_answer": state.conversation.final_answer,
            "final_state_snapshot": state.model_dump(mode="json"),
            "event_log": state.observability.events,
            "trace_summary": _trace_summary(compiled.compiled_app.services, state),
        }
        errors = [result["error"]] if result["error"] else []
        return AssemblyRunReport(
            assembly_id=compiled.spec.metadata.get("assembly_id", compiled.spec.agent.id),
            agent_id=compiled.spec.agent.id,
            status="failed" if errors else "passed",
            scenario_results=[result],
            errors=errors,
        )


def _error_from_state(state) -> dict[str, str] | None:
    if state.execution.finish_status == "completed":
        return None
    return {
        "message": state.execution.last_error or f"Runtime invocation ended as {state.execution.finish_status}.",
        "location": state.execution.last_error_location
        or state.execution.current_node
        or state.execution.current_subgraph
        or "runtime",
        "reason": "runtime_failed",
    }


def _trace_summary(services, state) -> dict | None:
    recorder = getattr(services, "trace_recorder", None)
    if recorder is None:
        return None
    return recorder.manifest_for(state.observability.trace_id)
