from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.models.message_layout import system_messages_first
from agent_factory.models.temporal_context import current_date_system_context
from agent_factory.create_agent.capability_inventory import (
    render_static_capability_inventory,
)
from agent_factory.runtime_attachments import format_attachments_for_model


@dataclass(frozen=True, slots=True)
class CreateAgentPromptPayload:
    messages: list[BaseMessage]
    diagnostics: dict[str, Any]


def build_create_agent_messages(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    capability_inventory: dict[str, Any] | None = None,
) -> list[BaseMessage]:
    return build_create_agent_prompt(
        state,
        tools,
        capability_inventory=capability_inventory,
    ).messages


def build_create_agent_prompt(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    capability_inventory: dict[str, Any] | None = None,
) -> CreateAgentPromptPayload:
    invariant_text = _invariant_system_prompt_text()
    stable_environment_text = _stable_environment_prompt_text(
        tools=tools,
        capability_inventory=capability_inventory or {},
    )
    stable_system_text = "\n\n".join([invariant_text, stable_environment_text])
    dynamic_system_text = _dynamic_system_context_text(state=state)
    projected_messages = list(state.get("messages") or [])
    stable_system = SystemMessage(content=stable_system_text)
    messages = system_messages_first([
        stable_system,
        *([SystemMessage(content=dynamic_system_text)] if dynamic_system_text else []),
        *projected_messages,
    ])
    diagnostics = {
        "version": "create_agent_prompt_diagnostics.v0",
        "section_digests": {
            "invariant_system": _digest_text(invariant_text),
            "stable_environment": _digest_text(stable_environment_text),
            "stable_system": _digest_text(stable_system_text),
            "dynamic_system": _digest_text(dynamic_system_text),
            "projected_history": _digest_messages(projected_messages),
            "full_prompt_projection": _digest_messages(messages),
        },
        "section_lengths": {
            "invariant_system_chars": len(invariant_text),
            "stable_environment_chars": len(stable_environment_text),
            "stable_system_chars": len(stable_system_text),
            "dynamic_system_chars": len(dynamic_system_text),
            "projected_history_messages": len(projected_messages),
            "projected_history_chars": sum(len(_message_content_text(message)) for message in projected_messages),
        },
        "tool_names_digest": _digest_json(_stable_tool_names(tools)),
        "tool_count": len(tools),
        "message_count": len(messages),
    }
    return CreateAgentPromptPayload(
        messages=messages,
        diagnostics=diagnostics,
    )


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _digest_json(value: Any) -> str:
    return _digest_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _digest_messages(messages: list[BaseMessage]) -> str:
    return _digest_json(
        [
            {
                "type": message.__class__.__name__,
                "content": _message_content_text(message),
                "name": str(getattr(message, "name", "") or ""),
            }
            for message in messages
        ]
    )


def _message_content_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(content)


def _invariant_system_prompt_text() -> str:
    sections = [
        "You are FastAgentFactory's create-agent ReAct authoring Agent. Build one RuntimeKernel AgentPackage "
        "directly in the supplied workspace. Use only bound tools for files, search, MCP, Skills, authoring, "
        "probing, and validation; do not run a separate SystemPackage manufacturing flow.",
        (
            "Load the manufacturing control Skill and inspect create_agent_stage before editing. Use set_focus "
            "only to intentionally correct the stage; deterministic authoring, probe, validation, and publish "
            "results synchronize focus automatically. Never directly read or write managed .factory state. "
            "Focus files are guidance, not write locks, and baseline scaffolding is owned by code and validators."
        ),
        (
            "When a resource or product decision truly requires user input, call "
            "create_agent_control(action='ask_user', message=...) immediately in the same model response that "
            "decides to ask. Never emit only question text or defer the tool call. If the question concerns a "
            "declared Resource, include resource_requests so the UI renders its value_schema. Treat resumed input "
            "as the user's actual answer; never invent a selection, confirmation, account, token, endpoint, or "
            "recipient. If the answer remains ambiguous, ask again in the user's language. Explanatory questions "
            "about status or configuration may be answered directly without ask_user or finalize."
        ),
        (
            "Do not hardcode business resources or secrets. Compare proposed capability against the Runtime "
            "Capability Inventory before promising support or requesting credentials. Public information may be "
            "discovered with bound tools; secrets can come only from the user."
        ),
        (
            "Use create_agent_authoring for managed identity, model bindings, pattern assembly, package tools, "
            "scheduler seeds, runtime Resources, and confirmed package knowledge. Apply one coherent capability "
            "increment instead of scattering manual edits. If validator evidence identifies a damaged scaffold-owned "
            "contract, use reset_contract. Package knowledge is opt-in and only for authoritative distributable "
            "material required at runtime; keep persona, prompts, behavior rules, and tool instructions in their "
            "own package surfaces. Never generate domain facts to fill knowledge."
        ),
        (
            "Assemble capabilities in this order: select a model and configure model bindings; materialize required "
            "inherited MCP; search, install, and verify reusable SkillHub capabilities; author package tools only "
            "for remaining execution gaps; then declare final runtime tool_access through pattern assembly. "
            "tool_bindings is a peer of bindings. Do not freeze assembly before the capability inventory is stable."
        ),
        (
            "For upsert_package_tool, provide a complete tool_spec containing id, description, input_schema, "
            "output_schema, resources, risk_level, concurrent, and optional output_compression, plus complete "
            "tool_source, requirements, a positive install_timeout_seconds, exposure nodes, and resource descriptors. "
            "Do not provide generated fields such as entrypoint, risk_evaluator, permission_scope, or permission_tags. "
            "tool_source must define synchronous run(arguments, resources). input_schema contains runtime arguments "
            "only. Preserve machine-significant long-output fields with action-specific compression schemas."
        ),
        (
            "Declare deployment configuration only through canonical Resource Descriptors using resource_id, "
            "description, required, value_schema, default_value, secret_fields, used_by, and "
            "sandbox_access_expectation. Keep default_value empty when configuration is deferred. Package tools must "
            "read Resources through matching selectors. User deliverables must use a declared workspace_root and be "
            "written to the current session workspace. Store complete user-supplied Resource values only through "
            "create_agent_resource; request missing fields through ask_user with resource_requests."
        ),
        (
            "For SkillHub reuse, first load 11-skillhub-system, identify the capability gap, check status, search with "
            "one to three short high-signal terms, compare candidates, install only an exact returned install_name, "
            "and verify the installed skill with skill(action='describe'). Load content or listed assets only when "
            "needed. Expose a registered skill-derived ToolSpec when available; otherwise use its guidance/assets "
            "with existing tools. Never copy a Skill into a package tool or hand-edit global extension registries."
        ),
        (
            "Use Skill Gateway resources progressively: describe a relevant Skill and read a relevant capability "
            "example, then author. Read schema fragments only when validator evidence identifies a concrete schema "
            "path or an example is insufficient. Read Skill resources only through skill(action='read_resource'); "
            "do not infer package schema from project source or shell inspection."
        ),
        (
            "Manufacturing tools and produced-Agent runtime tools are separate scopes. The supervisor has no generic "
            "shell. Add controlled runtime shell only when the produced Agent genuinely needs it. After a coherent "
            "capability increment, explicitly run create_agent_validate(scope='current_focus'). Validator evidence "
            "comes only from create_agent_validate observations or the latest validation digest in stage inspection."
        ),
        (
            "After adding or changing a package tool, inspect probeable tools and start a success_path probe with "
            "real arguments. The call returns an asynchronous job_id, not final evidence. Continue independent work "
            "and use status with wait_seconds when necessary; do not restart a progressing dependency build by "
            "changing timeout_seconds. Wait for a terminal probe state before claiming completion. Treat local_preflight, "
            "local_process, and local_timeout as runtime-environment blockers, not package-repair targets. Treat "
            "configuration_required as a valid deployment boundary, not an implementation failure."
        ),
        (
            "For inherited MCP, declare candidate tool IDs in pattern tool_access after model configuration, then "
            "call materialize_mcp_inheritance. Skip it when no inherited MCP is needed. Validation, probe, and publish "
            "do not rewrite MCP inheritance; rerun validation whenever the package fingerprint changes."
        ),
        (
            "Do not treat file reading as progress. Read only files needed for the current capability increment or "
            "identified by validator evidence. outside_focus is a warning, not a denial, when the file belongs to the "
            "same coherent change. output_id values must come from an explicit output_ref or tool_output(action='list'); "
            "never invent or reuse look-alike IDs."
        ),
        (
            "Finalization requires focus validation_publish, an explicit fresh "
            "create_agent_validate(scope='full_static'), and then create_agent_control(action='finalize') after it "
            "passes. finalize marks publish readiness; it does not physically publish. Physical publication occurs "
            "only through the user's Web confirmation panel. If the user requests further changes, implement them and "
            "repeat full_static validation and finalize."
        ),
    ]
    return "\n\n".join(sections)


def _stable_environment_prompt_text(
    *,
    tools: list[BaseTool],
    capability_inventory: dict[str, Any],
) -> str:
    sections = [
        "Stable create-agent manufacturing environment. This section should change only when configured tools or extension inventory changes.",
        f"Manufacturing tools bound to this ReAct loop only: {', '.join(_stable_tool_names(tools)) or 'none'}",
        render_static_capability_inventory(capability_inventory),
    ]
    return "\n\n".join(sections)


def _dynamic_system_context_text(
    *,
    state: Mapping[str, Any],
) -> str:
    task_analysis = _task_analysis_context(state)
    stage_context = build_authoring_stage_context(state)
    interaction_turn = _interaction_turn_context(state)
    attachments = format_attachments_for_model(state.get("runtime_attachments"))
    interrupt_answer = _interrupt_answer_context(state.get("interrupt_answer"))
    return "\n\n".join(
        item
        for item in [
            current_date_system_context(),
            task_analysis,
            stage_context,
            interaction_turn,
            interrupt_answer,
            attachments,
        ]
        if item
    )


def _interaction_turn_context(state: Mapping[str, Any]) -> str:
    messages = [message for message in state.get("messages") or [] if isinstance(message, BaseMessage)]
    latest_message = messages[-1] if messages else None
    has_new_user_input = isinstance(latest_message, HumanMessage)
    latest_role = str(getattr(latest_message, "type", "") or "none")
    return (
        "Create-agent interaction boundary:\n"
        f"latest_message_role: {latest_role}\n"
        f"new_user_input_available: {str(has_new_user_input).lower()}\n"
        "Only a latest HumanMessage is a new user reply. Tool observations and assistant text are not user confirmation. "
        "If a user decision is required and new_user_input_available is false, call "
        "create_agent_control(action='ask_user', message=...) now."
    )


def _interrupt_answer_context(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    question = str(value.get("question") or "").strip()
    input_text = str(value.get("input_text") or "").strip()
    if not input_text:
        return ""
    return (
        "Interrupt answer context (authoritative user input):\n"
        f"question: {question}\n"
        f"user_answer: {input_text}\n"
        "Treat this as user input only. Do not infer an unspecified choice or claim the user selected an option."
    )


def _task_analysis_context(state: Mapping[str, Any]) -> str:
    workspace_path = str(state.get("workspace_path") or "").strip()
    if not workspace_path:
        return ""
    path = Path(workspace_path) / ".factory" / "task_analysis.json"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    selected_pattern_id = str(payload.get("selected_pattern_id") or "").strip()
    digest = {
        "selected_pattern_id": selected_pattern_id,
        "requires_dynamic_plan": bool(payload.get("requires_dynamic_plan")),
        "intent_summary": str(payload.get("intent_summary") or ""),
        "capability_goals": payload.get("capability_goals") if isinstance(payload.get("capability_goals"), list) else [],
        "manufacturing_notes": payload.get("manufacturing_notes") if isinstance(payload.get("manufacturing_notes"), list) else [],
        "resource_requirements": payload.get("resource_requirements") if isinstance(payload.get("resource_requirements"), list) else [],
    }
    return (
        "Create-agent task analysis completed before scaffolding:\n"
        f"{json.dumps(digest, ensure_ascii=False, sort_keys=True)}\n"
        "The selected_pattern_id is the authoritative baseline runtime pattern for this workspace. "
        "If package files do not match it, call create_agent_authoring(action='configure_pattern_assembly') before adding unrelated capability work."
        + (
            " For plan_and_execute, configure planner, executor, final_answer delivery tools, runtime_plan bindings, and activation. "
            "Activation must state the workflow goal, what concrete user input starts the workflow, and what to ask when that input is missing."
            if selected_pattern_id == "plan_and_execute"
            else ""
        )
    )


def build_authoring_stage_context(state: Mapping[str, Any]) -> str:
    workspace_path = str(state.get("workspace_path") or "").strip()
    if not workspace_path:
        return ""
    path = Path(workspace_path) / ".factory" / "system_state.json"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    active_focus_id = str(payload.get("active_focus_id") or "")
    stages = payload.get("stages") if isinstance(payload.get("stages"), list) else []
    active = next(
        (item for item in stages if isinstance(item, dict) and item.get("system_id") == active_focus_id),
        {},
    )
    return (
        "Current authoring stage:\n"
        + json.dumps(
            {
                "workflow_kind": payload.get("workflow_kind", "manufacture"),
                "active_focus_id": active_focus_id,
                "focus_summary": active.get("focus_summary", ""),
                "suggested_skills": active.get("suggested_skills", []),
                "validation_focus": active.get("validation_focus", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\nLoad the relevant suggested skill for this stage before making its first material change."
    )


def _stable_tool_names(tools: list[BaseTool]) -> list[str]:
    return sorted(str(tool.name) for tool in tools)
