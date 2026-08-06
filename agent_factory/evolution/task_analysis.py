from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.create_agent.models import EvolutionTaskAnalysis
from agent_factory.create_agent.task_analysis import invoke_structured_task_analysis
from agent_factory.models import get_main_model, get_task_model


def analyze_evolution_task(
    *,
    user_input: str,
    package_summary: dict[str, Any],
    trace_context: dict[str, Any],
    model: Any | None = None,
) -> EvolutionTaskAnalysis:
    classifier = model or get_task_model() or get_main_model()
    if classifier is None:
        raise RuntimeError("agent evolution task analysis requires a configured task or main model")
    analysis = invoke_structured_task_analysis(
        classifier=classifier,
        schema=EvolutionTaskAnalysis,
        messages=_analysis_messages(
            user_input=user_input,
            package_summary=package_summary,
            trace_context=trace_context,
        ),
        analysis_name="agent evolution task analysis",
    )
    current_pattern = str(package_summary.get("pattern_id") or "").strip()
    if "assembly_pattern_system" not in analysis.affected_systems and current_pattern in {"react_agent", "plan_and_execute"}:
        analysis = analysis.model_copy(update={"selected_pattern_id": current_pattern})
    return analysis


def _analysis_messages(
    *,
    user_input: str,
    package_summary: dict[str, Any],
    trace_context: dict[str, Any],
) -> list[Any]:
    return [
        SystemMessage(
            content=(
                "Analyze one requested evolution of an existing AgentPackage. Return JSON only using the supplied "
                "EvolutionTaskAnalysis schema. Preserve every package system not affected by the user goal. Derive "
                "affected_systems and capability_changes semantically from the goal and current package, rather than "
                "matching isolated keywords. The selected_pattern_id must reflect the existing package unless the user "
                "explicitly requests an orchestration change. Decide model and model-tool requirements before custom "
                "tool authoring: image generation/editing and other auxiliary modalities should use a compatible model "
                "tool when available. tool_source_decisions must evaluate existing built-ins, inherited MCP, SkillHub, "
                "and package-owned code in that order; package code is only for a remaining governed execution gap. "
                "Infer resource_requirements for stable deployment configuration such as accounts, credentials, API keys, "
                "mailboxes, database connections, fixed endpoints, and default delivery destinations. These are not tool "
                "call arguments. Each requirement must include a value_schema with known enum/range/length constraints, "
                "secret_fields, used_by tool ids, and sandbox_access_expectation. Never propose embedding resource values "
                "in source, prompts, or ToolSpec input_schema. Failed trace context is evidence only when relevant to the "
                "goal or required validation. Do not generate implementation steps.\n\n"
                f"EvolutionTaskAnalysis JSON schema:\n{json.dumps(EvolutionTaskAnalysis.model_json_schema(), ensure_ascii=False, sort_keys=True)}"
            )
        ),
        HumanMessage(
            content=json.dumps(
                {
                    "user_evolution_goal": user_input,
                    "current_package": package_summary,
                    "trace_context": trace_context,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        ),
    ]
