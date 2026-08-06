from __future__ import annotations

from typing import Any

from langgraph.errors import GraphInterrupt

from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.patterns.node_observability import emit_state_event
from agent_factory.runtime_kernel.patterns.state_patches import (
    merge_patches,
    validate_package_state_patch,
    validate_wrapper_patch_sections,
)
from agent_factory.runtime_kernel.patterns.schema import PatternNodeWrapperSpec
from agent_factory.runtime_kernel.state import RuntimeState, merge_state_patch
from agent_factory.runtime_kernel.state_contracts import PackageStateManager
from agent_factory.runtime_kernel.wrappers import NodeWrapperRegistry


def execute_with_retries(
    state: RuntimeState,
    context: NodeExecutionContext,
    execute,
) -> dict[str, Any]:
    attempts = 0
    while True:
        try:
            return execute(state, context)
        except GraphInterrupt:
            raise
        except Exception:
            attempts += 1
            state.execution.retry_count += 1
            if attempts > state.execution.max_retries:
                raise


def run_system_before(
    *,
    stage: str,
    wrappers: list[Any],
    state: RuntimeState,
    context: NodeExecutionContext,
) -> tuple[RuntimeState, dict[str, Any]]:
    working = state
    cumulative_patch: dict[str, Any] = {}
    for wrapper in wrappers:
        if getattr(wrapper, "before_stage", None) != stage:
            continue
        result = wrapper.before(state=working, context=context)
        if result is None:
            continue
        if not isinstance(result, tuple) or len(result) != 2:
            raise RuntimeKernelError(f"system wrapper {wrapper.wrapper_id} returned invalid before result")
        next_state, patch = result
        working = next_state
        cumulative_patch.update(patch or {})
    return working, cumulative_patch


def run_system_after(
    *,
    wrappers: list[Any],
    state: RuntimeState,
    context: NodeExecutionContext,
    node_result: dict[str, Any],
    duration_ms: int,
) -> None:
    for wrapper in wrappers:
        after = getattr(wrapper, "after", None)
        if after is None:
            continue
        after(state=state, context=context, node_result=node_result, duration_ms=duration_ms)


def run_system_on_error(
    *,
    wrappers: list[Any],
    state: RuntimeState,
    context: NodeExecutionContext,
    error: Exception,
) -> None:
    for wrapper in wrappers:
        on_error = getattr(wrapper, "on_error", None)
        if on_error is None:
            continue
        on_error(state=state, context=context, error=error)


def run_node_wrappers(
    *,
    phase: str,
    state: RuntimeState,
    context: NodeExecutionContext,
    wrapper_specs: list[PatternNodeWrapperSpec],
    wrapper_registry: NodeWrapperRegistry,
    services: RuntimeServices,
    package_state_manager: PackageStateManager | None,
    node_result: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> tuple[RuntimeState, dict[str, Any]]:
    working = state
    cumulative_patch: dict[str, Any] = {}
    for spec in [item for item in wrapper_specs if item.phase == phase]:
        wrapper = wrapper_registry.create(spec)
        location = f"{context.node_id}.{phase}.{spec.id}"
        emit_state_event(
            services,
            working,
            "wrapper_started",
            node_id=context.node_id,
            payload={"wrapper_id": spec.id, "phase": phase, "location": location},
        )
        try:
            if phase == "before":
                patch = wrapper.before(state=working, context=context, config=dict(spec.config))
            elif phase == "after":
                patch = wrapper.after(
                    state=working,
                    context=context,
                    config=dict(spec.config),
                    node_result=node_result or {},
                )
            elif phase == "on_error":
                patch = wrapper.on_error(
                    state=working,
                    context=context,
                    config=dict(spec.config),
                    error=error or RuntimeError("Unknown node error."),
                )
            else:
                raise RuntimeKernelError(f"Unsupported node wrapper phase: {phase}")
            patch = patch or {}
            validate_wrapper_patch_sections(spec.id, wrapper.writable_sections, patch)
            validate_package_state_patch(package_state_manager, context.node_id, patch)
            if patch:
                working = merge_state_patch(working, patch)
                cumulative_patch = merge_patches(cumulative_patch, patch)
            emit_state_event(
                services,
                working,
                "wrapper_completed",
                node_id=context.node_id,
                payload={"wrapper_id": spec.id, "phase": phase, "location": location},
            )
        except Exception as exc:
            working.execution.last_error_location = location
            emit_state_event(
                services,
                working,
                "wrapper_failed",
                node_id=context.node_id,
                payload={"wrapper_id": spec.id, "phase": phase, "location": location, "error": str(exc)},
            )
            raise
    return working, cumulative_patch


def run_pre_hooks(state: RuntimeState, context: NodeExecutionContext) -> tuple[RuntimeState, dict[str, Any]]:
    updated = state.model_copy(deep=True)
    patch: dict[str, Any] = {}
    if context.impl.startswith("cognitive."):
        prompt_binding = first_binding_payload(context.bindings, "prompt")
        updated.context.model_context = context.services.context_engine.build_model_context(
            state=updated,
            binding=prompt_binding,
        )
        updated.context.assembly_log.append(f"auto_pre_cognitive:{context.node_id}")
        patch["context"] = updated.context.model_dump(mode="json")
    elif context.impl.startswith("operational."):
        tool_binding = first_binding_payload(context.bindings, "tool_access")
        updated.context.tool_context = context.services.context_engine.build_tool_context(
            state=updated,
            binding=tool_binding,
        )
        updated.context.assembly_log.append(f"auto_pre_operational:{context.node_id}")
        patch["context"] = updated.context.model_dump(mode="json")
    for hook in sorted(context.hook_bindings, key=lambda item: int(item.get("order", 0))):
        point = hook.get("hook_point")
        if context.impl.startswith("cognitive.") and point == "pre_cognitive":
            prompt_binding = first_binding_payload(context.bindings, "prompt")
            updated.context.model_context = context.services.context_engine.build_model_context(
                state=updated,
                binding=prompt_binding,
            )
            updated.context.assembly_log.append(f"pre_cognitive:{context.node_id}")
            patch["context"] = updated.context.model_dump(mode="json")
        elif context.impl.startswith("operational.") and point == "pre_operational":
            tool_binding = first_binding_payload(context.bindings, "tool_access")
            updated.context.tool_context = context.services.context_engine.build_tool_context(
                state=updated,
                binding=tool_binding,
            )
            updated.context.assembly_log.append(f"pre_operational:{context.node_id}")
            patch["context"] = updated.context.model_dump(mode="json")
        elif context.impl.startswith("terminal.") and point == "pre_terminal":
            updated.observability.debug_refs.append({"kind": "hook", "phase": point, "node_id": context.node_id})
            patch["observability"] = updated.observability.model_dump(mode="json")
    return updated, patch


def run_post_hooks(state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    debug_refs: list[dict[str, Any]] = []
    for hook in sorted(context.hook_bindings, key=lambda item: int(item.get("order", 0))):
        point = hook.get("hook_point")
        if point in {"post_cognitive", "post_operational", "post_terminal"}:
            debug_refs.append({"kind": "hook", "phase": point, "node_id": context.node_id})
        elif point == "on_interrupt" and (state.policy.interrupted or state.execution.interrupted):
            debug_refs.append({"kind": "hook", "phase": point, "node_id": context.node_id})
        elif point == "on_resume" and state.execution.resume_payload:
            debug_refs.append({"kind": "hook", "phase": point, "node_id": context.node_id})
    if debug_refs:
        patch["observability"] = {"debug_refs": [*state.observability.debug_refs, *debug_refs]}
    if context.impl.startswith("terminal.") or context.impl == "finalize":
        formatter = first_binding_payload(context.bindings, "output_formatter")
        if formatter and formatter.get("mode") == "prefix" and state.conversation.final_answer:
            patch.setdefault("conversation", {})
            patch["conversation"]["final_answer"] = f"{formatter.get('config', {}).get('prefix', '')}{state.conversation.final_answer}"
    return patch


def first_binding_payload(bindings: list[dict[str, Any]], binding_type: str) -> dict[str, Any] | None:
    for binding in bindings:
        if binding.get("binding_type") == binding_type:
            return dict(binding.get("payload") or {})
    return None
