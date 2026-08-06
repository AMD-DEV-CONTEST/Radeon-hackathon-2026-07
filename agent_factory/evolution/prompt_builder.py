from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.create_agent.capability_inventory import render_static_capability_inventory
from agent_factory.create_agent.prompt_builder import CreateAgentPromptPayload, build_authoring_stage_context
from agent_factory.models.message_layout import system_messages_first


def build_evolution_messages(
    *,
    package_id: str,
    package_path: str,
    user_input: str,
    error_pack: dict[str, Any],
    trace_gate: dict[str, Any] | None = None,
    target_plan: dict[str, Any] | None = None,
    task_analysis: dict[str, Any] | None = None,
    package_summary: dict[str, Any],
    tools: list[Any],
) -> list[BaseMessage]:
    tool_names = ", ".join(str(getattr(tool, "name", "")) for tool in tools)
    system = f"""You are FastAgentFactory's evolution runtime for a published Agent.

Your task is to modify one published AgentPackage according to the user's evolution goal. A failed-trace error summary, when supplied, is supporting evidence rather than the default objective.

Mandatory constraints:
- The user_evolution_goal is the primary objective. Work from it and the current package state.
- failed_trace_error_pack may be absent. When present, address it only if it directly relates to the user goal or blocks validation, probing, or runtime readiness.
- If both the user goal and trace evidence require work, explain their relationship, complete the user goal first, and fix trace issues that block publication.
- Modify only files inside the current published package directory: {package_path}
- Do not create a new Agent or scaffold again. Reuse the manufacturing task analysis, stage state, authoring, probe, and validation architecture on the existing package.
- Do not read a complete trace or expose manufacturing tools, workspaces, or trace details. Use only the supplied error summary.
- Make structural changes on the package surface that owns the behavior: prompts, contracts, tool implementation, dependencies, attachment handling, or context policy.
- Do not create short-, medium-, and long-term plans. Complete one coherent publishable evolution.
- When evidence is limited, inspect only the necessary package surface and make a conservative general solution; never hardcode one-off examples.
- Before the first edit, load skill(action="load", name="00-agent-evolution", current_system="agent_evolution", reason=...), then inspect create_agent_stage and load the active focus's suggested evolution Skill.
- The evolution task analysis is the structured change contract. affected_systems and capability_changes define the write surface, preserved_systems must remain intact, and resource_requirements belong in Resource Descriptors rather than tool arguments or source code.
- Progress through requirement_focus -> capability_implementation -> experience_assembly -> validation_publish. Use stage inspection or intentional focus correction and let deterministic authoring, probe, and validation results synchronize state.
- evolution_target_plan provides runtime blockers and execution guidance. If authoring lacks a required field, report the authoring gap instead of bypassing managed protection with generic edit/write.
- Before adding or changing a Package Tool, classify accounts, credentials, API keys, email, database connections, fixed endpoints, and default recipients as deployment Resources when appropriate. Declare canonical descriptors, align ToolSpec resource selectors, and read values only from resources. Never place them in input_schema or hardcode them.
- Resource Descriptor JSON Schema belongs in value_schema. When configuration is deferred, submit the descriptor with an empty default_value. Do not create placeholder accounts, keys, or endpoints.
- Every added or changed package tool requires a fresh success-path probe through create_agent_probe_tool inspect and call.
- If full_static validation fails, continue the ReAct repair from validator evidence instead of repeating a failure summary.
- After full_static passes, call create_agent_control(action="finalize", message=...) with an English evolution summary. After finalize, do not emit another summary or call more tools; the runtime uses that message as the sole terminal report.

Available tools: {tool_names}
"""
    user = {
        "package_id": package_id,
        "package_path": package_path,
        "user_evolution_goal": user_input,
        "package_summary": package_summary,
        "trace_gate": trace_gate or {},
        "evolution_target_plan": target_plan or {},
        "evolution_task_analysis": task_analysis or {},
        **(
            {"failed_trace_error_pack": error_pack}
            if error_pack
            else {
                "failed_trace_error_pack": {
                    "provided": False,
                    "reason": str((trace_gate or {}).get("reason") or "trace details were not provided; use the user goal and package state only"),
                }
            }
        ),
    }
    return [
        SystemMessage(content=system),
        HumanMessage(content=json.dumps(user, ensure_ascii=False, indent=2)),
    ]


def build_evolution_prompt(
    state: dict[str, Any],
    tools: list[BaseTool],
    *,
    capability_inventory: dict[str, Any] | None = None,
) -> CreateAgentPromptPayload:
    context = state.get("evolution_context") if isinstance(state.get("evolution_context"), dict) else {}
    messages = system_messages_first([
        *build_evolution_messages(
            package_id=str(context.get("package_id") or ""),
            package_path=str(state.get("workspace_path") or context.get("package_path") or ""),
            user_input=str(state.get("request") or ""),
            error_pack=context.get("error_pack") if isinstance(context.get("error_pack"), dict) else {},
            trace_gate=context.get("trace_gate") if isinstance(context.get("trace_gate"), dict) else {},
            package_summary=context.get("package_summary") if isinstance(context.get("package_summary"), dict) else {},
            target_plan=context.get("target_plan") if isinstance(context.get("target_plan"), dict) else {},
            task_analysis=context.get("task_analysis") if isinstance(context.get("task_analysis"), dict) else {},
            tools=tools,
        ),
        *list(state.get("messages") or []),
    ])
    stage_context = build_authoring_stage_context(state)
    if stage_context:
        messages = system_messages_first([messages[0], SystemMessage(content=stage_context), *messages[1:]])
    stable = {
        "tool_names": sorted(str(getattr(tool, "name", "")) for tool in tools),
        "capability_inventory": render_static_capability_inventory(capability_inventory or {}),
    }
    return CreateAgentPromptPayload(
        messages=messages,
        diagnostics={
            "version": "agent_evolution_prompt_diagnostics.v0",
            "tool_count": len(tools),
            "message_count": len(messages),
            "stable_environment": stable,
        },
    )
