from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.runtime import RunControl
from langgraph.types import Command

from agent_factory.memory_system.config import should_enqueue_memory_write
from agent_factory.memory_system.reports import memory_event_payload
from agent_factory.memory_system.segment import build_conversation_segment
from agent_factory.memory_system.schema import MemoryWriteJob
from agent_factory.memory_system.scopes import MemoryScopeContext, local_memory_user_id
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids
from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.state.checkpoint_projection import runtime_checkpoint_payload
from agent_factory.tooling.execution_context import runtime_run_control_context, tool_output_session_context
from agent_factory.local_inference.request_context import inference_request_context


LANGGRAPH_TECHNICAL_RECURSION_LIMIT = 1000


class ExecutionController:
    def __init__(self) -> None:
        pass

    def run(self, compiled_app: Any, state: RuntimeState, *, thread_id: str) -> RuntimeState:
        with (
            tool_output_session_context(state.run.session_id),
            runtime_run_control_context(None),
            inference_request_context(session_id=state.run.session_id),
        ):
            self._emit(
                compiled_app,
                state,
                "run_started",
                message="Kernel run started.",
                payload={
                    "agent_id": state.run.agent_id,
                    "pattern_id": state.run.pattern_id,
                    "pattern_version": state.run.pattern_version,
                },
            )
            state, graph_messages = self._invoke_graph(compiled_app, state, thread_id=thread_id)
            self._enqueue_memory_write(compiled_app, state, thread_id=thread_id, messages=graph_messages)
            self._emit_run_completed(compiled_app, state)
            return state

    def stream(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        control: RunControl | None = None,
    ) -> Iterator[tuple[str, Any]]:
        with (
            tool_output_session_context(state.run.session_id),
            runtime_run_control_context(control),
            inference_request_context(session_id=state.run.session_id),
        ):
            self._emit(
                compiled_app,
                state,
                "run_started",
                message="Kernel run started.",
                payload={
                    "agent_id": state.run.agent_id,
                    "pattern_id": state.run.pattern_id,
                    "pattern_version": state.run.pattern_version,
                },
            )
            final_raw: dict[str, Any] = {"runtime": state.model_dump(mode="python")}
            graph_messages: list[Any] = []
            for stream_mode, chunk in self._stream_graph(
                compiled_app,
                state,
                thread_id=thread_id,
                control=control,
            ):
                if stream_mode == "values" and isinstance(chunk, dict):
                    final_raw = chunk
                    graph_messages = list(chunk.get("messages") or [])
                yield stream_mode, chunk
            final_raw = _authoritative_raw(compiled_app, final_raw, thread_id=thread_id)
            graph_messages = list(final_raw.get("messages") or graph_messages)
            result = self._final_state_from_raw(final_raw, messages=graph_messages)
            memory_event = self._enqueue_memory_write(compiled_app, result, thread_id=thread_id, messages=graph_messages)
            if memory_event is not None:
                yield "custom", memory_event
            self._emit_run_completed(compiled_app, result)
            yield "runtime_final", result

    def stream_resume(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        resume_payload: dict[str, Any] | None = None,
        control: RunControl | None = None,
    ) -> Iterator[tuple[str, Any]]:
        with (
            tool_output_session_context(state.run.session_id),
            runtime_run_control_context(control),
            inference_request_context(session_id=state.run.session_id),
        ):
            state = _prepare_resume_state(state, resume_payload=resume_payload)
            self._emit(compiled_app, state, "resume_started", message="Kernel resume started.")
            final_raw: dict[str, Any] = {"runtime": state.model_dump(mode="python")}
            graph_messages: list[Any] = []
            for stream_mode, chunk in self._stream_graph(
                compiled_app,
                state,
                thread_id=thread_id,
                stream_input=Command(resume=resume_payload or {}),
                control=control,
            ):
                if stream_mode == "values" and isinstance(chunk, dict):
                    final_raw = chunk
                    graph_messages = list(chunk.get("messages") or [])
                yield stream_mode, chunk
            final_raw = _authoritative_raw(compiled_app, final_raw, thread_id=thread_id)
            graph_messages = list(final_raw.get("messages") or graph_messages)
            result = self._final_state_from_raw(final_raw, messages=graph_messages)
            memory_event = self._enqueue_memory_write(compiled_app, result, thread_id=thread_id, messages=graph_messages)
            if memory_event is not None:
                yield "custom", memory_event
            self._emit(compiled_app, result, "resume_completed", message="Kernel resumed from checkpoint.")
            self._emit_run_completed(compiled_app, result)
            yield "runtime_final", result

    def resume(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        resume_payload: dict[str, Any] | None = None,
    ) -> RuntimeState:
        with tool_output_session_context(state.run.session_id):
            state = _prepare_resume_state(state, resume_payload=resume_payload)
            self._emit(compiled_app, state, "resume_started", message="Kernel resume started.")
            state, graph_messages = self._invoke_graph(
                compiled_app,
                state,
                thread_id=thread_id,
                graph_input=Command(resume=resume_payload or {}),
            )
            self._enqueue_memory_write(compiled_app, state, thread_id=thread_id, messages=graph_messages)
            self._emit(compiled_app, state, "resume_completed", message="Kernel resumed from checkpoint.")
            self._emit_run_completed(compiled_app, state)
            return state

    def _invoke_graph(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        graph_input: Any | None = None,
    ) -> tuple[RuntimeState, list[Any]]:
        raw = compiled_app.graph_app.invoke(
            _graph_input(state) if graph_input is None else graph_input,
            config=_graph_config(state, thread_id=thread_id),
        )
        raw = _authoritative_raw(compiled_app, raw, thread_id=thread_id)
        messages = list(raw.get("messages") or [])
        return self._final_state_from_raw(raw, messages=messages), messages

    def _stream_graph(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        stream_input: Any | None = None,
        control: RunControl | None = None,
    ) -> Iterator[tuple[str, Any]]:
        yield from compiled_app.graph_app.stream(
            _graph_input(state) if stream_input is None else stream_input,
            config=_graph_config(state, thread_id=thread_id),
            stream_mode=["updates", "values", "debug", "custom"],
            durability="sync",
            control=control,
        )

    def _final_state_from_raw(self, raw: dict[str, Any], *, messages: list[Any] | None = None) -> RuntimeState:
        result = RuntimeState.model_validate(raw.get("runtime") or {})
        if result.execution.interrupted or result.policy.interrupted:
            result.execution.finished = True
            result.execution.finish_status = "interrupted"
            return result
        missing_tool_call_ids = incomplete_tool_call_ids(list(messages or raw.get("messages") or []))
        if missing_tool_call_ids:
            result.execution.finished = True
            result.execution.finish_status = "failed"
            result.execution.last_error = (
                "Runtime graph ended with incomplete tool call history: "
                f"missing_tool_call_ids={missing_tool_call_ids}"
            )
            result.execution.last_error_location = "runtime.finalize"
            return result
        if not result.execution.finished:
            result.execution.finished = True
            result.execution.finish_status = "failed"
            result.execution.last_error = result.execution.last_error or "Runtime graph ended before a terminal node."
            result.execution.last_error_location = result.execution.last_error_location or "runtime.finalize"
        return result

    def _emit_run_completed(self, compiled_app: Any, state: RuntimeState) -> None:
        failed = state.execution.finish_status == "failed"
        self._emit(
            compiled_app,
            state,
            "run_failed" if failed else "run_completed",
            message=state.execution.last_error if failed else (state.execution.finish_status or "completed"),
            payload={
                "finish_status": state.execution.finish_status or "completed",
                "turn_count": state.execution.turn_count,
                "error": state.execution.last_error,
                "where": state.execution.last_error_location,
            },
        )

    def _emit(
        self,
        compiled_app: Any,
        state: RuntimeState,
        event_type: str,
        *,
        node_id: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        subgraph_id: str | None = None,
    ) -> None:
        event = RuntimeObservationEvent(
            trace_id=state.observability.trace_id,
            run_id=state.run.run_id,
            event_type=event_type,
            node_id=node_id,
            subgraph_id=subgraph_id,
            message=message,
            payload=payload or {},
        )
        compiled_app.services.observability_manager.emit(event)
        state.observability.events.append(event.model_dump(mode="json"))
        trace_recorder = getattr(compiled_app.services, "trace_recorder", None)
        if trace_recorder is not None:
            trace_recorder.ensure_trace(
                trace_id=state.observability.trace_id,
                run_id=state.run.run_id,
                agent_id=state.run.agent_id,
                session_id=state.run.session_id,
            )
            if (
                event_type == "run_failed"
                and isinstance(payload, dict)
                and str(payload.get("where") or "").startswith("runtime.")
            ):
                trace_recorder.suppress_trace(
                    trace_id=state.observability.trace_id,
                    run_id=state.run.run_id,
                    reason="runtime_finalize_failure",
                    payload={
                        "event_type": event_type,
                        "error": state.execution.last_error,
                        "where": payload.get("where"),
                        "finish_status": payload.get("finish_status"),
                    },
                )
                return
            trace_recorder.record_event(
                trace_id=state.observability.trace_id,
                run_id=state.run.run_id,
                event_type=event_type,
                node_id=node_id,
                message=message,
                payload=payload or {},
                status=str(payload.get("finish_status")) if isinstance(payload, dict) and payload.get("finish_status") else None,
            )
            if event_type in {"run_completed", "run_failed"}:
                trace_recorder.finish_trace(
                    trace_id=state.observability.trace_id,
                    status="failed" if event_type == "run_failed" else "completed",
                )

    def _enqueue_memory_write(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        messages: list[Any],
    ) -> dict[str, Any] | None:
        if state.execution.finish_status != "completed" or state.execution.last_error:
            return None
        runtime = getattr(compiled_app.services, "memory_system", None)
        writer = getattr(runtime, "writer", None)
        if runtime is None or writer is None:
            return None
        if not getattr(runtime.config, "enabled", False) or not getattr(runtime.config, "write_enabled", False):
            return None
        turn_index = int(state.conversation.turn_index or 0)
        if not should_enqueue_memory_write(turn_index=turn_index, config=runtime.config):
            return None
        workspace_id = str(state.run.workspace_id or "").strip()
        scope_context = MemoryScopeContext(
            agent_id=str(runtime.agent_id or state.run.agent_id),
            user_id=str(runtime.user_id or local_memory_user_id()),
            workspace_id=workspace_id or None,
        )
        available_namespaces = scope_context.namespaces()
        namespace = available_namespaces.get("workspace") or available_namespaces["agent"]
        memory_scope = "workspace" if workspace_id else "agent"
        source = {
            "agent_id": state.run.agent_id,
            "session_id": state.run.session_id,
            "workspace_id": workspace_id or None,
            "thread_id": thread_id,
            "run_id": state.run.run_id,
            "node_id": state.execution.current_node,
        }
        segment = build_conversation_segment(
            scope=memory_scope,
            namespace=namespace,
            source=source,
            messages=messages or _messages_delta(state),
            end_turn=turn_index,
            max_user_turns=runtime.config.background.write_interval_turns,
        )
        if segment is None:
            return None
        job = MemoryWriteJob(
            scope=memory_scope,
            namespace=namespace,
            available_namespaces=available_namespaces,
            source=source,
            segment=segment,
        )
        try:
            report = writer.enqueue(job)
            event_type = "memory_write_queued" if report.status == "queued" else "memory_write_queued_failed"
            payload = {"event_type": event_type, **memory_event_payload(report)}
            self._emit(
                compiled_app,
                state,
                event_type,
                message=report.status,
                payload=payload,
            )
            return {"type": "memory_event", "payload": payload}
        except Exception as exc:
            payload = {
                "event_type": "memory_write_queued_failed",
                "namespace": list(tuple(runtime.namespace)),
                "error": f"{type(exc).__name__}: {exc}",
            }
            self._emit(
                compiled_app,
                state,
                "memory_write_queued_failed",
                message=f"{type(exc).__name__}: {exc}",
                payload=payload,
            )
            return {"type": "memory_event", "payload": payload}


def _messages_delta(state: RuntimeState) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if state.conversation.current_user_input:
        messages.append({"role": "user", "content": state.conversation.current_user_input})
    assistant_text = state.conversation.final_answer or state.conversation.assistant_draft
    if assistant_text:
        messages.append({"role": "assistant", "content": assistant_text})
    return messages


def _prepare_resume_state(state: RuntimeState, *, resume_payload: dict[str, Any] | None) -> RuntimeState:
    state.execution.finished = False
    state.execution.finish_status = None
    state.execution.interrupted = False
    state.execution.resume_payload = resume_payload or {}
    state.policy.interrupted = False
    state.policy.interrupt_required = False
    state.policy.approval_required = False
    return state


def _graph_input(state: RuntimeState) -> dict[str, Any]:
    payload: dict[str, Any] = {"runtime": runtime_checkpoint_payload(state, mode="python")}
    user_input = (state.conversation.current_user_input or "").strip()
    if user_input:
        payload["messages"] = [HumanMessage(content=user_input)]
    return payload


def _graph_config(state: RuntimeState, *, thread_id: str) -> dict[str, Any]:
    return {
        "recursion_limit": LANGGRAPH_TECHNICAL_RECURSION_LIMIT,
        "configurable": {"thread_id": thread_id},
    }


def _authoritative_raw(compiled_app: Any, raw: dict[str, Any], *, thread_id: str) -> dict[str, Any]:
    """Merge stream output with the persisted LangGraph checkpoint.

    Stream chunks are transport updates. The checkpointer state is the
    authoritative protocol state for the messages channel, especially for
    assistant tool-call/tool-observation pairing.
    """
    values = _checkpoint_values(compiled_app, thread_id=thread_id)
    if not values:
        return raw
    merged = dict(raw)
    checkpoint_messages = values.get("messages")
    if checkpoint_messages is not None:
        merged["messages"] = checkpoint_messages
    if not merged.get("runtime") and values.get("runtime") is not None:
        merged["runtime"] = values["runtime"]
    return merged


def _checkpoint_values(compiled_app: Any, *, thread_id: str) -> dict[str, Any]:
    try:
        snapshot = compiled_app.graph_app.get_state({"configurable": {"thread_id": thread_id}})
    except Exception:
        return {}
    values = getattr(snapshot, "values", {}) or {}
    if isinstance(values, dict):
        return dict(values)
    return {}
