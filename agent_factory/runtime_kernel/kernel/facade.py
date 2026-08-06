from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agent_factory.context_system.runtime import default_context_runtime
from agent_factory.runtime_kernel.adapters import InMemoryToolRegistry
from agent_factory.memory_system import (
    MemoryStoreRuntimeConfig,
    MemorySystemConfig,
    default_agent_memory_config,
    default_agent_runtime,
)
from agent_factory.memory_system.background import MemoryBackgroundWorker
from agent_factory.memory_system.store_index import build_memory_store_index
from agent_factory.runtime_kernel.bindings import BindingSet, RuntimeServices
from agent_factory.runtime_kernel.bookmarks import InMemoryBookmarkStore
from agent_factory.runtime_kernel.context import ContextEngine
from agent_factory.runtime_kernel.execution import ExecutionController
from agent_factory.runtime_protocol.completion import runtime_completed
from agent_factory.runtime_kernel.kernel.models import CompiledKernelApp, RuntimeKernelInstance
from agent_factory.runtime_kernel.kernel.compile_support import (
    ensure_memory_runtime,
    required_services_for_pattern,
    resolve_render_manifest,
)
from agent_factory.runtime_kernel.kernel.run_context import (
    RuntimeKernelRunContext,
    configure_memory_runtime_for_agent,
    initial_package_state,
    session_manager_from_config,
    state_for_new_turn,
)
from agent_factory.runtime_kernel.nodes.registry import NodeRegistry
from agent_factory.runtime_kernel.node_providers import NodeProvider
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.runtime_kernel.nodes.standard import (
    CognitiveAnswerNode,
    CognitiveClarifyNode,
    CognitiveIntentGateNode,
    CognitivePlanNode,
    CognitiveReviewNode,
    CognitiveRouteNode,
    CognitiveStructuredNode,
    FinalizeNode,
    IngressNode,
    OperationalResourceProbeNode,
    OperationalToolCallNode,
    TerminalCloseNode,
    TerminalCommitNode,
)
from agent_factory.runtime_kernel.observability import ObservabilityManager
from agent_factory.runtime_kernel.patterns.compiler import PatternCompiler
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.patterns.validator import PatternValidator
from agent_factory.runtime_kernel.persistence import (
    LangGraphCheckpointerConfig,
    LangGraphCheckpointerFactory,
    LangGraphStoreConfig,
    LangGraphStoreFactory,
)
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.runtime_kernel.state import (
    ContextState,
    ConversationState,
    ExecutionState,
    ObservabilityState,
    PolicyState,
    RunState,
    RuntimeConfigState,
    RuntimeState,
    ToolState,
)
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager
from agent_factory.runtime_render import RenderManifest
from agent_factory.runtime_kernel.wrappers.system_registry import DEFAULT_RUNTIME_SYSTEM_WRAPPER_IDS
from agent_factory.trace_system import runtime_trace_ref


class RuntimeKernelFacade:
    @classmethod
    def for_contract_runtime(
        cls,
        *,
        builtins_dir: str | Path | None = None,
        session_config: AgentSessionConfig | None = None,
    ) -> "RuntimeKernelFacade":
        """Build a kernel whose persistent services are assembled by the App runtime.

        AgentPackage compilation contributes the fixed session infrastructure
        and the context-owned cross-session memory runtime. Bootstrap services
        therefore stay in-memory instead of opening duplicate persistent stores.
        """

        bootstrap_memory = default_agent_memory_config().model_copy(
            update={
                "enabled": False,
                "write_enabled": False,
                "injection_enabled": False,
                "store": MemoryStoreRuntimeConfig(backend="memory"),
            },
            deep=True,
        )
        return cls(
            builtins_dir=builtins_dir,
            checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
            memory_system_config=bootstrap_memory,
            session_config=session_config,
        )

    def __init__(
        self,
        *,
        builtins_dir: str | Path | None = None,
        checkpointer_config: LangGraphCheckpointerConfig | None = None,
        memory_store_config: LangGraphStoreConfig | None = None,
        memory_system_config: MemorySystemConfig | dict | None = None,
        session_config: AgentSessionConfig | None = None,
    ) -> None:
        builtins_dir = builtins_dir or Path(__file__).resolve().parents[1] / "patterns" / "builtins"
        node_registry = NodeRegistry()
        for impl in [
            IngressNode(),
            CognitiveClarifyNode(),
            CognitiveIntentGateNode(),
            CognitivePlanNode(),
            CognitiveRouteNode(),
            CognitiveStructuredNode(),
            CognitiveAnswerNode(),
            CognitiveReviewNode(),
            OperationalToolCallNode(),
            OperationalResourceProbeNode(),
            TerminalCommitNode(),
            TerminalCloseNode(),
            FinalizeNode(),
        ]:
            node_registry.register(impl)
        pattern_registry = PatternRegistry(builtins_dir=builtins_dir)
        validator = PatternValidator()
        compiler = PatternCompiler(node_registry=node_registry, pattern_registry=pattern_registry, validator=validator)
        controller = ExecutionController()
        checkpointer = LangGraphCheckpointerFactory().build(
            checkpointer_config
            or LangGraphCheckpointerConfig(
                backend="sqlite",
                path=Path(".agent_runtime/checkpoints/agent.sqlite"),
            )
        ).saver
        memory_config = (
            memory_system_config
            if isinstance(memory_system_config, MemorySystemConfig)
            else MemorySystemConfig.model_validate(memory_system_config or default_agent_memory_config().model_dump(mode="json"))
        )
        resolved_memory_store_config = memory_store_config or LangGraphStoreConfig(
            backend=memory_config.store.backend,
            path=(
                Path(memory_config.store.path)
                if memory_config.store.backend == "sqlite" and memory_config.store.path.strip()
                else None
            ),
            connection_uri=memory_config.store.connection_uri,
            database_name=memory_config.store.database_name,
            collection_name=memory_config.store.collection_name,
            setup=memory_config.store.setup,
            provider_options=memory_config.store.provider_options,
            index=build_memory_store_index(memory_config),
        )
        memory_store = LangGraphStoreFactory().build(resolved_memory_store_config).store
        memory_runtime = default_agent_runtime(
            agent_id="default-agent",
            config=memory_config,
            store=memory_store,
        )
        self.background_workers = RuntimeBackgroundWorkerManager()
        self._default_memory_worker: MemoryBackgroundWorker | None = None
        if memory_config.write_enabled:
            worker = MemoryBackgroundWorker(store=memory_store, config=memory_config)
            memory_runtime.writer = worker
            self._default_memory_worker = worker
            self.background_workers.add(worker)
        services = RuntimeServices(
            model_service=None,
            model_operation_service=ModelOperationService(role="main"),
            tool_registry=InMemoryToolRegistry(),
            memory_store=memory_store,
            memory_system=memory_runtime,
            context_system=default_context_runtime(),
            context_engine=ContextEngine(),
            observability_manager=ObservabilityManager(),
            checkpointer=checkpointer,
            bookmark_store=InMemoryBookmarkStore(),
        )
        self.session_manager = AgentSessionManager(session_config)
        self.instance = RuntimeKernelInstance(
            services=services,
            node_registry=node_registry,
            pattern_registry=pattern_registry,
            validator=validator,
            compiler=compiler,
            controller=controller,
        )

    def compile(
        self,
        *,
        pattern_id: str,
        bindings: BindingSet | None = None,
        services: RuntimeServices | None = None,
        render_manifest: RenderManifest | dict | None = None,
        system_wrapper_ids: list[str] | tuple[str, ...] | None = None,
        node_providers: list[NodeProvider] | tuple[NodeProvider, ...] | None = None,
    ) -> CompiledKernelApp:
        services = services or self.instance.services
        if services is self.instance.services:
            self._start_default_background_workers()
        bindings = bindings or BindingSet()
        if node_providers:
            self.register_node_providers(node_providers)
        pattern = self.instance.pattern_registry.get(pattern_id)
        resolved_render_manifest = resolve_render_manifest(pattern, render_manifest)
        ensure_memory_runtime(services)
        services.validate_required(required_services_for_pattern(pattern))
        return self.instance.compiler.compile(
            pattern_id=pattern_id,
            bindings=bindings,
            services=services,
            render_manifest=resolved_render_manifest,
            system_wrapper_ids=DEFAULT_RUNTIME_SYSTEM_WRAPPER_IDS if system_wrapper_ids is None else system_wrapper_ids,
            package_state_manager=None,
        )

    def register_node_providers(self, providers: list[NodeProvider] | tuple[NodeProvider, ...]) -> None:
        registered_impl_ids: list[str] = []
        for provider in providers:
            for implementation in provider.implementations():
                if self.instance.node_registry.has(implementation.impl_id):
                    existing = self.instance.node_registry.get(implementation.impl_id)
                    if existing is implementation:
                        continue
                    raise RuntimeError(f"node implementation already registered: {implementation.impl_id}")
                self.instance.node_registry.register(implementation)
                registered_impl_ids.append(implementation.impl_id)
        if registered_impl_ids:
            self.instance.pattern_registry.register_node_impl_ids(registered_impl_ids)

    def _start_default_background_workers(self) -> None:
        if self._default_memory_worker is None:
            return
        events = self.background_workers.start_all()
        if any(event.status == "failed" and event.worker_type == "MemoryBackgroundWorker" for event in events):
            memory_system = getattr(self.instance.services, "memory_system", None)
            if memory_system is not None:
                memory_system.writer = None

    def shutdown(self) -> None:
        self.background_workers.shutdown_all()

    def run(
        self,
        compiled: CompiledKernelApp,
        *,
        user_input: str,
        user_config: dict | None = None,
        agent_config: dict | None = None,
        session_config: dict | None = None,
    ) -> RuntimeState:
        run_context = self.prepare_run_context(
            compiled,
            user_input=user_input,
            user_config=user_config,
            agent_config=agent_config,
            session_config=session_config,
        )
        result = self.instance.controller.run(compiled, run_context.state, thread_id=run_context.thread_id)
        if runtime_completed(result):
            run_context.session_manager.touch_turn(
                run_context.session_id,
                first_user_input=run_context.first_user_input,
                user_input=run_context.first_user_input,
                final_answer=_session_final_answer(result),
                status=result.execution.finish_status,
                trace_ref=_session_trace_ref(compiled, result),
            )
        return result

    def stream(
        self,
        compiled: CompiledKernelApp,
        *,
        user_input: str,
        user_config: dict | None = None,
        agent_config: dict | None = None,
        session_config: dict | None = None,
    ) -> Iterator[tuple[str, Any]]:
        run_context = self.prepare_run_context(
            compiled,
            user_input=user_input,
            user_config=user_config,
            agent_config=agent_config,
            session_config=session_config,
        )
        final_state: RuntimeState | None = None
        for item in self.instance.controller.stream(compiled, run_context.state, thread_id=run_context.thread_id):
            if item[0] == "runtime_final":
                final_state = item[1]
            yield item
        if runtime_completed(final_state):
            run_context.session_manager.touch_turn(
                run_context.session_id,
                first_user_input=run_context.first_user_input,
                user_input=run_context.first_user_input,
                final_answer=_session_final_answer(final_state),
                status=final_state.execution.finish_status,
                trace_ref=_session_trace_ref(compiled, final_state),
            )

    def prepare_run_context(
        self,
        compiled: CompiledKernelApp,
        *,
        user_input: str,
        user_config: dict | None = None,
        agent_config: dict | None = None,
        session_config: dict | None = None,
    ) -> RuntimeKernelRunContext:
        agent_config = dict(agent_config or {})
        session_config = dict(session_config or {})
        agent_id = str(agent_config.get("agent_id") or compiled.metadata.get("agent_id") or compiled.pattern_spec.pattern_id)
        session_manager = session_manager_from_config(session_config, default=self.session_manager)
        session_id = str(session_config.get("session_id") or "").strip()
        if session_id:
            session = session_manager.load_optional(session_id)
            if session is None and not bool(session_config.get("create_session_if_missing")):
                raise FileNotFoundError(f"Agent session not found: {session_id}")
        else:
            session = None
        if session is None:
            session = session_manager.create(
                agent_id=agent_id,
                session_id=session_id or None,
                first_user_input=user_input,
                session_kind=str(session_config.get("session_kind") or "normal"),
                visible_in_agent_session_list=session_config.get("visible_in_agent_session_list"),
            )
        elif session.agent_id != agent_id:
            raise ValueError(
                f"Agent session belongs to {session.agent_id}, expected {agent_id}: {session.session_id}"
            )
        state = state_for_new_turn(compiled, thread_id=session.thread_id)
        state.run = RunState(
            agent_id=agent_id,
            session_id=session.session_id,
            workspace_id=session.workspace_id,
            pattern_id=compiled.pattern_spec.pattern_id,
            pattern_version=compiled.pattern_spec.version,
        )
        state.conversation = ConversationState(
            current_user_input=user_input,
            turn_index=int(session.turn_count or 0),
        )
        state.context = ContextState()
        state.tools = ToolState()
        state.policy = PolicyState()
        state.execution = ExecutionState()
        state.observability = ObservabilityState()
        state.runtime_config = RuntimeConfigState()
        state.runtime_config.user_config = dict(user_config or {})
        state.runtime_config.agent_config = agent_config
        state.runtime_config.session_config = {
            **session_config,
            "session_id": session.session_id,
            "thread_id": session.thread_id,
            "workspace_id": session.workspace_id,
        }
        configure_memory_runtime_for_agent(compiled.services, agent_id)
        return RuntimeKernelRunContext(
            state=state,
            thread_id=session.thread_id,
            session_manager=session_manager,
            session_id=session.session_id,
            first_user_input=user_input,
        )

    def resume(
        self,
        compiled: CompiledKernelApp,
        *,
        session_id: str,
        resume_payload: dict | None = None,
        session_config: dict | None = None,
    ) -> RuntimeState:
        run_context = self.prepare_resume_context(
            compiled,
            session_id=session_id,
            session_config=session_config,
        )
        return self.instance.controller.resume(
            compiled,
            run_context.state,
            thread_id=run_context.thread_id,
            resume_payload=resume_payload,
        )

    def stream_resume(
        self,
        compiled: CompiledKernelApp,
        *,
        session_id: str,
        resume_payload: dict | None = None,
        session_config: dict | None = None,
    ) -> Iterator[tuple[str, Any]]:
        run_context = self.prepare_resume_context(
            compiled,
            session_id=session_id,
            session_config=session_config,
        )
        final_state: RuntimeState | None = None
        for item in self.instance.controller.stream_resume(
            compiled,
            run_context.state,
            thread_id=run_context.thread_id,
            resume_payload=resume_payload,
        ):
            if item[0] == "runtime_final":
                final_state = item[1]
            yield item
        if runtime_completed(final_state):
            run_context.session_manager.touch_turn(
                run_context.session_id,
                request_id=run_context.session_turn_request_id,
                final_answer=_session_final_answer(final_state),
                status=final_state.execution.finish_status,
                trace_ref=_session_trace_ref(compiled, final_state),
            )

    def prepare_resume_context(
        self,
        compiled: CompiledKernelApp,
        *,
        session_id: str,
        session_config: dict | None = None,
    ) -> RuntimeKernelRunContext:
        session_manager = session_manager_from_config(session_config or {}, default=self.session_manager)
        session = session_manager.load(session_id)
        state = RuntimeState()
        state.package_state = initial_package_state(compiled)
        state.run.agent_id = session.agent_id
        state.run.session_id = session.session_id
        state.run.workspace_id = session.workspace_id
        state.run.pattern_id = compiled.pattern_spec.pattern_id
        state.run.pattern_version = compiled.pattern_spec.version
        state.runtime_config.session_config = {
            **dict(session_config or {}),
            "session_id": session.session_id,
            "thread_id": session.thread_id,
            "workspace_id": session.workspace_id,
        }
        configure_memory_runtime_for_agent(compiled.services, session.agent_id)
        return RuntimeKernelRunContext(
            state=state,
            thread_id=session.thread_id,
            session_manager=session_manager,
            session_id=session.session_id,
            first_user_input=session.first_user_input or "",
            session_turn_request_id=_latest_session_turn_request_id(session),
        )


def _session_final_answer(state: RuntimeState | None) -> str | None:
    if state is None:
        return None
    conversation = getattr(state, "conversation", None)
    if conversation is None:
        return None
    return str(
        getattr(conversation, "final_answer", None)
        or getattr(conversation, "assistant_draft", None)
        or ""
    ).strip() or None


def _latest_session_turn_request_id(session: Any) -> str | None:
    turns = list(getattr(session, "turns", ()) or ())
    if not turns:
        return None
    request_id = str(getattr(turns[-1], "request_id", "") or "").strip()
    return request_id or None


def _session_trace_ref(compiled: CompiledKernelApp, state: RuntimeState | None) -> dict[str, str] | None:
    if state is None:
        return None
    trace_id = str(getattr(getattr(state, "observability", None), "trace_id", "") or "").strip()
    run_id = str(getattr(getattr(state, "run", None), "run_id", "") or "").strip()
    recorder = getattr(compiled.services, "trace_recorder", None)
    return runtime_trace_ref(recorder=recorder, trace_id=trace_id, run_id=run_id)
