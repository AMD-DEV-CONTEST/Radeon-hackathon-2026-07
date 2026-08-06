from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.models import get_task_model
from agent_factory.tooling.spec import ToolRiskAction, ToolRiskLevel, ToolRiskResult


ToolRiskEvaluator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | ToolRiskResult]


class LLMRiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ToolRiskAction = "uncertain"
    risk_level: ToolRiskLevel | None = None
    reasons: list[str] = Field(default_factory=list)


def call_llm_risk_evaluator(
    *,
    tool_id: str,
    base_risk_level: ToolRiskLevel,
    prompt: str,
    arguments: dict[str, Any],
    context: dict[str, Any],
    hard_result: ToolRiskResult | None = None,
) -> ToolRiskResult:
    model = get_task_model()
    if model is None:
        return ToolRiskResult(
            action="uncertain",
            risk_level=base_risk_level,
            reasons=["task model is not configured for llm risk evaluation"],
        )
    structured_model = model.with_structured_output(LLMRiskDecision, method="json_mode").with_config(
        tags=["nostream", "tool-risk"]
    )
    raw_decision = structured_model.invoke(
        [
            SystemMessage(
                content=(
                    "You are the small-task model used only for tool argument risk evaluation. "
                    "You do not execute tools and you cannot approve a hard deny. "
                    "Return JSON only. Allowed action values: allow, ask, deny, uncertain."
                )
            ),
            HumanMessage(
                content=json.dumps(
                    {
                        "tool_id": tool_id,
                        "base_risk_level": base_risk_level,
                        "risk_prompt": prompt,
                        "arguments": arguments,
                        "context": context,
                        "hard_result": hard_result.model_dump(mode="json") if hard_result else None,
                    },
                    ensure_ascii=False,
                )
            ),
        ]
    )
    decision = raw_decision if isinstance(raw_decision, LLMRiskDecision) else LLMRiskDecision.model_validate(raw_decision)
    return ToolRiskResult(
        action=decision.action,
        risk_level=decision.risk_level,
        reasons=decision.reasons,
        facts={"llm_risk_model": "task"},
    )


def merge_risk_results(results: list[ToolRiskResult], *, base_risk_level: ToolRiskLevel) -> ToolRiskResult:
    if not results:
        return ToolRiskResult(action="inherit", risk_level=base_risk_level)
    reasons: list[str] = []
    facts: dict[str, Any] = {}
    normalized_arguments: dict[str, Any] | None = None
    for result in results:
        reasons.extend(result.reasons)
        facts.update(result.facts)
        if result.normalized_arguments is not None:
            normalized_arguments = result.normalized_arguments
    action = _strongest_action([result.action for result in results])
    risk_level = _strongest_risk_level(
        [result.risk_level for result in results if result.risk_level is not None],
        base_risk_level=base_risk_level,
    )
    return ToolRiskResult(
        action=action,
        risk_level=risk_level,
        reasons=reasons,
        facts=facts,
        normalized_arguments=normalized_arguments,
    )


def _strongest_action(actions: list[str]) -> str:
    for candidate in ("deny", "ask", "uncertain", "allow"):
        if candidate in actions:
            return candidate
    return "inherit"


def _strongest_risk_level(levels: list[ToolRiskLevel], *, base_risk_level: ToolRiskLevel) -> ToolRiskLevel:
    order = {"low": 0, "medium": 1, "high": 2}
    strongest = base_risk_level
    for level in levels:
        if order[level] > order[strongest]:
            strongest = level
    return strongest
