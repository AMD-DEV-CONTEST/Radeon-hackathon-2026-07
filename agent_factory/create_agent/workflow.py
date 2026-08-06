from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from agent_factory.create_agent.models import CreateAgentAction, PackageValidationReport
from agent_factory.create_agent.output_safety import looks_like_internal_observation_text
from agent_factory.create_agent.prompt_builder import build_create_agent_prompt
from agent_factory.create_agent.resource_contract import load_resource_descriptors, resource_request_payloads
from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.models import get_main_model
from agent_factory.models.content import content_to_text
from agent_factory.model_pool.runtime_override import resolve_runtime_main_chat_model_from_state
from agent_factory.resource_system import ResourceStore
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.tooling.langgraph_node import (
    build_tool_node_runner,
    latest_ai_declared_tool_calls,
    latest_ai_tool_calls,
)


class CreateAgentGraphState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    request: str
    workspace_path: str
    runtime_attachments: list[dict[str, Any]]
    iteration: int
    validation: dict[str, Any]
    graph_kind: str
    evolution_context: dict[str, Any]
    runtime_main_model_profile_id: str
    runtime_reasoning_intensity: int | None
    flow_status: Literal["running", "turn_complete", "package_complete"]
    final_answer: str
    publish_ready: dict[str, Any]
    interrupt_answer: dict[str, Any]


@dataclass(slots=True)
class CreateAgentWorkflow:
    tools: list[BaseTool]
    model: Any | None = None
    capability_inventory: dict[str, Any] | None = None
    workflow_kind: Literal["manufacture", "evolution"] = "manufacture"

    def compile(self, *, checkpointer: Any | None = None):
        graph = StateGraph(CreateAgentGraphState)
        graph.add_node("supervisor", self._supervisor)
        graph.add_node("tools", self._tools)
        graph.add_node("control_gate", self._control_gate)
        graph.set_entry_point("supervisor")
        graph.add_conditional_edges(
            "supervisor",
            self._route_after_supervisor,
            {"tools": "tools", "control_gate": "control_gate"},
        )
        graph.add_conditional_edges(
            "tools",
            self._route_after_tools,
            {"supervisor": "supervisor", "control_gate": "control_gate"},
        )
        graph.add_conditional_edges(
            "control_gate",
            self._route_after_control_gate,
            {"supervisor": "supervisor", "end": END},
        )
        return graph.compile(checkpointer=checkpointer)

    def _supervisor(self, state: CreateAgentGraphState) -> dict[str, Any]:
        _ai_message, unresolved_tool_calls = latest_ai_tool_calls(state.get("messages") or [])
        if unresolved_tool_calls:
            return {
                "flow_status": "running",
            }
        runtime_model = resolve_runtime_main_chat_model_from_state(state)
        model = runtime_model.model if runtime_model is not None else self.model or get_main_model()
        if model is None:
            raise RuntimeError("main model is not configured for create-agent")
        if self.workflow_kind == "evolution":
            from agent_factory.evolution.prompt_builder import build_evolution_prompt

            prompt_payload = build_evolution_prompt(
                state,
                self.tools,
                capability_inventory=self.capability_inventory or {},
            )
            node_id = "evolution_supervisor"
        else:
            prompt_payload = build_create_agent_prompt(
                state,
                self.tools,
                capability_inventory=self.capability_inventory or {},
            )
            node_id = "create_agent_supervisor"
        messages = prompt_payload.messages
        prompt_binding, chat_messages = _operation_prompt(messages)
        result = ModelOperationService(
            role="main",
            model=model,
            settings=runtime_model.settings if runtime_model is not None else None,
        ).tool_bound_chat(
            state=state,
            prompt_binding=prompt_binding,
            messages=chat_messages,
            tools=self.tools,
            node_id=node_id,
        )
        _emit_model_cache_metrics(
            state=state,
            workspace=CreateAgentWorkspace(state["workspace_path"]),
            metadata=result.metadata,
            prompt_diagnostics=prompt_payload.diagnostics,
        )
        response = result.ai_message if isinstance(result.ai_message, BaseMessage) else AIMessage(content=result.assistant_draft or "")
        return {
            "messages": [response],
            "iteration": int(state.get("iteration") or 0) + 1,
        }

    def _tools(self, state: CreateAgentGraphState) -> dict[str, Any]:
        tool_node = build_tool_node_runner(
            self.tools,
            node_id="create_agent_tools",
            messages_key="messages",
            emit_event=_emit_tool_activity,
        )
        result = tool_node.invoke(state)
        return result

    def _control_gate(self, state: CreateAgentGraphState) -> dict[str, Any]:
        workspace = CreateAgentWorkspace(state["workspace_path"])
        if self.workflow_kind == "evolution":
            return self._evolution_control_gate(state, workspace)
        publish_report = workspace.read_publish_report()
        if publish_report.get("status") == "available":
            package_id = str(publish_report.get("package_id") or "").strip()
            package_path = str(publish_report.get("package_path") or "").strip()
            return {
                "flow_status": "package_complete",
                "final_answer": f"AgentPackage published: {package_id} ({package_path})",
            }
        action = workspace.read_action()
        if action.action == "ask_user":
            return self._interrupt_for_user(
                workspace,
                action=action,
                interrupt_type="create_agent_question",
                title="Additional manufacturing information",
                default_message="Please provide the information required to manufacture this AgentPackage.",
            )
        assistant_turn = _assistant_turn_without_tools(state)
        if assistant_turn is not None:
            return _turn_complete_result(assistant_turn)
        if action.action != "finalize":
            return {"flow_status": "running"}
        report = workspace.read_validation()
        ready_error = _publish_readiness_error(workspace=workspace, report=report)
        if ready_error:
            workspace.write_action(CreateAgentAction())
            return {
                "messages": [SystemMessage(content=ready_error)],
                "flow_status": "running",
            }
        workspace.write_action(CreateAgentAction())
        return _publish_ready_result(workspace, report)

    def _evolution_control_gate(self, state: CreateAgentGraphState, workspace: CreateAgentWorkspace) -> dict[str, Any]:
        action = workspace.read_action()
        if action.action == "ask_user":
            return self._interrupt_for_user(
                workspace,
                action=action,
                interrupt_type="agent_evolution_question",
                title="Additional evolution information",
                default_message="Please provide the information required to evolve this published AgentPackage.",
            )
        assistant_turn = _assistant_turn_without_tools(state)
        if assistant_turn is not None:
            return _turn_complete_result(assistant_turn)
        if action.action != "finalize":
            return {"flow_status": "running"}
        report = workspace.read_validation()
        ready_error = _evolution_publish_readiness_error(workspace=workspace, report=report)
        if ready_error:
            workspace.write_action(CreateAgentAction())
            return {
                "messages": [SystemMessage(content=ready_error)],
                "flow_status": "running",
            }
        final_answer = _evolution_final_answer(action.message)
        workspace.write_action(CreateAgentAction())
        return {
            "validation": report.to_digest().model_dump(mode="json"),
            "flow_status": "package_complete",
            "final_answer": final_answer,
        }

    @staticmethod
    def _interrupt_for_user(
        workspace: CreateAgentWorkspace,
        *,
        action: CreateAgentAction,
        interrupt_type: str,
        title: str,
        default_message: str,
    ) -> dict[str, Any]:
        question = action.message or default_message
        answer = interrupt(
            {
                "type": interrupt_type,
                "presentation": "assistant_dialogue",
                "resume_kind": "answer",
                "title": title,
                "message": question,
                "workspace_id": workspace.root.name,
                "workspace_path": str(workspace.root),
                "resource_facts": [fact.model_dump(mode="json") for fact in action.resource_facts],
                "resource_requests": resource_request_payloads(workspace, action.resource_requests),
            }
        )
        workspace.write_action(CreateAgentAction())
        previous_report = workspace.read_validation() or PackageValidationReport(
            package_root=str(workspace.root),
            validation_scope="workspace_hygiene",
            skipped=True,
            summary="Validation skipped while waiting for user input.",
        )
        return {
            "messages": [_resume_message(answer, question=question, interrupt_type=interrupt_type)],
            "interrupt_answer": _interrupt_answer_context(
                answer,
                question=question,
                interrupt_type=interrupt_type,
            ),
            "validation": previous_report.to_digest().model_dump(mode="json"),
            "flow_status": "running",
        }

    def _route_after_supervisor(self, state: CreateAgentGraphState) -> Literal["tools", "control_gate"]:
        _ai_message, tool_calls = latest_ai_tool_calls(state.get("messages") or [])
        return "tools" if tool_calls else "control_gate"

    def _route_after_tools(self, state: CreateAgentGraphState) -> Literal["supervisor", "control_gate"]:
        _ai_message, tool_calls = latest_ai_declared_tool_calls(state.get("messages") or [])
        return "control_gate" if _has_control_action(tool_calls) else "supervisor"

    def _route_after_control_gate(self, state: CreateAgentGraphState) -> Literal["supervisor", "end"]:
        return "end" if state.get("flow_status") in {"turn_complete", "package_complete"} else "supervisor"


def _emit_tool_activity(payload: dict[str, Any]) -> None:
    writer = get_stream_writer()
    writer({"type": "tool_activity", "payload": {"events": [payload]}})


def _emit_model_cache_metrics(
    *,
    state: CreateAgentGraphState,
    workspace: CreateAgentWorkspace,
    metadata: dict[str, Any],
    prompt_diagnostics: dict[str, Any],
) -> None:
    usage = metadata.get("usage_metadata") if isinstance(metadata.get("usage_metadata"), dict) else {}
    input_tokens = _usage_int(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_int(usage, "output_tokens", "completion_tokens")
    cached_input_tokens = _cached_input_tokens(usage)
    hit_ratio = None
    if input_tokens and cached_input_tokens is not None:
        hit_ratio = round(float(cached_input_tokens) / float(input_tokens), 6)
    active = workspace.read_system_state().active_stage()
    graph_kind = str(state.get("graph_kind") or "manufacture")
    evolution_context = state.get("evolution_context") if isinstance(state.get("evolution_context"), dict) else {}
    agent_id = "agent_evolution" if graph_kind == "evolution" else "create_agent"
    agent_name = "Evolution Agent" if graph_kind == "evolution" else "Manufacturing Agent"
    payload = {
        "version": "create_agent_model_cache_metrics.v0",
        "node_id": "create_agent_supervisor",
        "iteration": int(state.get("iteration") or 0) + 1,
        "active_focus_id": active.system_id if active else None,
        "active_focus_status": active.status.value if active else None,
        "provider_cache": {
            "available": cached_input_tokens is not None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "hit_ratio": hit_ratio,
            "source": "usage_metadata.input_token_details.cache_read" if cached_input_tokens is not None else None,
        },
        "prompt_diagnostics": prompt_diagnostics,
        "model": metadata.get("model"),
        "provider": metadata.get("provider"),
        "provider_display_name": metadata.get("provider_display_name"),
        "model_profile_id": metadata.get("model_profile_id"),
        "model_role": metadata.get("model_role"),
        "model_source": metadata.get("model_source"),
        "agent_id": agent_id,
        "agent_name": agent_name,
        "package_id": evolution_context.get("package_id") if graph_kind == "evolution" else None,
        "session_id": state.get("session_id"),
        "run_id": state.get("request_id"),
        "tool_count": metadata.get("tool_count"),
    }
    writer = get_stream_writer()
    writer({"type": "create_agent_model_cache", "payload": payload})


def _usage_int(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _cached_input_tokens(usage: dict[str, Any]) -> int | None:
    details = usage.get("input_token_details")
    if isinstance(details, dict):
        value = details.get("cache_read")
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _has_control_action(tool_calls: list[dict[str, Any]]) -> bool:
    return any(str(call.get("name") or "") == "create_agent_control" for call in tool_calls)


def _assistant_turn_without_tools(state: CreateAgentGraphState) -> str | None:
    ai_message, tool_calls = latest_ai_declared_tool_calls(state.get("messages") or [])
    if ai_message is None or tool_calls:
        return None
    return content_to_text(ai_message.content).strip()


def _turn_complete_result(assistant_text: str) -> dict[str, Any]:
    if not assistant_text:
        raise RuntimeError("create-agent model returned neither a tool call nor a user-visible answer")
    return {
        "flow_status": "turn_complete",
        "final_answer": assistant_text,
    }


def _publish_readiness_error(*, workspace: CreateAgentWorkspace, report: PackageValidationReport | None) -> str:
    active = workspace.read_system_state().active_stage()
    if active is None or active.system_id != "validation_publish":
        return (
            "Finalize blocked: active focus must be validation_publish. "
            "Run create_agent_validate(scope='full_static', reason=...) after implementation is complete; "
            "a passed full_static validation synchronizes validation_publish readiness."
        )
    if report is None:
        return "Finalize blocked: no validation report exists. Call create_agent_validate(scope='full_static', reason=...) first."
    if report.status != "passed":
        return (
            f"Finalize blocked: latest validation status is {report.status}. "
            "Repair from the create_agent_validate observation, then call create_agent_validate(scope='full_static', reason=...) again."
        )
    validation_state = workspace.read_validation_state()
    if validation_state is None:
        return "Finalize blocked: validation fingerprint state is missing. Call create_agent_validate(scope='full_static', reason=...) again."
    if validation_state.validation_scope != "full_static" or report.validation_scope != "full_static":
        return "Finalize blocked: latest validation must be full_static. Call create_agent_validate(scope='full_static', reason=...) first."
    if validation_state.package_fingerprint != package_fingerprint(workspace.root):
        return "Finalize blocked: package files changed after validation. Call create_agent_validate(scope='full_static', reason=...) again."
    return ""


def _evolution_publish_readiness_error(*, workspace: CreateAgentWorkspace, report: PackageValidationReport | None) -> str:
    if report is None:
        return "Finalize blocked: no validation report exists. Call create_agent_validate(scope='full_static', reason=...) first."
    if report.status != "passed":
        return (
            f"Finalize blocked: latest validation status is {report.status}. "
            "Repair from the create_agent_validate observation, then call create_agent_validate(scope='full_static', reason=...) again."
        )
    validation_state = workspace.read_validation_state()
    if validation_state is None:
        return "Finalize blocked: validation fingerprint state is missing. Call create_agent_validate(scope='full_static', reason=...) again."
    if validation_state.validation_scope != "full_static" or report.validation_scope != "full_static":
        return "Finalize blocked: latest validation must be full_static. Call create_agent_validate(scope='full_static', reason=...) first."
    if validation_state.package_fingerprint != package_fingerprint(workspace.root):
        return "Finalize blocked: package files changed after validation. Call create_agent_validate(scope='full_static', reason=...) again."
    return ""


def _resume_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("input_text", "answer", "message"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return str(value)
    return str(value or "").strip()


def _resume_message(value: Any, *, question: str, interrupt_type: str) -> HumanMessage:
    """Keep an interrupt answer typed without changing the model-visible text."""
    payload = value if isinstance(value, dict) else {}
    return HumanMessage(
        content=_resume_text(value),
        additional_kwargs={
            "message_source": "user",
            "message_kind": "interrupt_answer",
            "interrupt_type": interrupt_type,
            "interrupt_id": str(payload.get("interrupt_id") or "").strip(),
            "interrupt_question": str(question or "").strip(),
        },
    )


def _interrupt_answer_context(value: Any, *, question: str, interrupt_type: str) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    return {
        "message_source": "user",
        "message_kind": "interrupt_answer",
        "interrupt_type": interrupt_type,
        "interrupt_id": str(payload.get("interrupt_id") or "").strip(),
        "question": str(question or "").strip(),
        "input_text": _resume_text(value),
    }


def _evolution_final_answer(message: str) -> str:
    text = str(message or "").strip()
    if text and not looks_like_internal_observation_text(text):
        return text
    return "AgentPackage evolution passed full_static validation, completed, and was published automatically."


def _operation_prompt(messages: list[BaseMessage]) -> tuple[dict[str, Any], list[BaseMessage]]:
    if messages and isinstance(messages[0], SystemMessage):
        return {"template": str(messages[0].content or "")}, messages[1:]
    return {}, messages


def _publish_ready_text(
    workspace: CreateAgentWorkspace,
    report: PackageValidationReport,
    runtime_configuration: dict[str, Any] | None = None,
) -> str:
    pending = list((runtime_configuration or {}).get("pending_resources") or [])
    pending_text = ""
    if pending:
        resource_ids = ", ".join(str(item.get("resource_id") or "") for item in pending if isinstance(item, dict))
        pending_text = (
            f"\n- Runtime Resources: {resource_ids} are not configured and can be completed in package details after publication.\n"
        )
    return (
        "AgentPackage manufacturing is complete and final static validation passed.\n\n"
        f"- Workspace: {workspace.root}\n"
        f"- Validation: {report.validation_scope} / {report.status}\n"
        f"- Summary: {report.summary}\n"
        f"{pending_text}\n"
        "The package is ready for publication. Use the confirmation panel below to publish or continue editing."
    )


def _publish_ready_payload(workspace: CreateAgentWorkspace, report: PackageValidationReport) -> dict[str, Any]:
    runtime_configuration = _runtime_configuration_status(workspace)
    return {
        "version": "agent_package_publish_report.v0",
        "status": "ready",
        "workspace_id": workspace.root.name,
        "source_workspace": str(workspace.root),
        "message": _publish_ready_text(workspace, report, runtime_configuration),
        "validation": report.to_digest().model_dump(mode="json"),
        "runtime_configuration": runtime_configuration,
        "package_fingerprint": package_fingerprint(workspace.root),
    }


def _publish_ready_result(workspace: CreateAgentWorkspace, report: PackageValidationReport) -> dict[str, Any]:
    publish_ready = _publish_ready_payload(workspace, report)
    workspace.write_publish_report(publish_ready)
    return {
        "validation": report.to_digest().model_dump(mode="json"),
        "publish_ready": publish_ready,
        "flow_status": "package_complete",
        "final_answer": str(publish_ready["message"]),
    }


def _runtime_configuration_status(workspace: CreateAgentWorkspace) -> dict[str, Any]:
    descriptors = load_resource_descriptors(workspace)
    statuses = ResourceStore().status(workspace.root.name, descriptors)
    pending = [
        {
            "resource_id": str(item.get("resource_id") or ""),
            "description": str(item.get("description") or ""),
            "required": bool(item.get("required")),
            "used_by": list(item.get("used_by") or []),
        }
        for item in statuses
        if item.get("required") and not item.get("configured")
    ]
    return {
        "status": "required" if pending else "ready",
        "pending_resources": pending,
    }
