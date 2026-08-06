from __future__ import annotations

from typing import Any

from agent_factory.tooling.envelope import tool_envelope, tool_failure
from agent_factory.tooling.skillhub.search_query import normalize_skillhub_search_query
from agent_factory.tooling.spec import ToolRiskResult


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get("skillhub")
    if runtime is None or not hasattr(runtime, "run"):
        return tool_failure(
            "SkillHUB runtime is not configured",
            output={"status": "failed"},
        )
    try:
        result = runtime.run(_normalized_payload(arguments))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return tool_failure(error, output={"status": "failed"})
    if str(result.get("status") or "").strip() == "failed":
        error = str(result.get("error") or result.get("message") or "SkillHUB action failed").strip()
        return tool_failure(error, output=result)
    return tool_envelope(
        result,
        summary=str(result.get("message") or "SkillHUB action completed."),
    )


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    try:
        normalized = _normalized_payload(arguments)
    except ValueError as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[str(exc)],
        ).model_dump(mode="json")
    action = str(normalized.get("action") or "")
    if action in {"status", "search"}:
        return ToolRiskResult(
            action="allow",
            risk_level="low",
            reasons=[f"read-only SkillHUB action: {action}"],
            normalized_arguments=normalized,
        ).model_dump(mode="json")
    if action in {"install", "remove"}:
        return ToolRiskResult(
            action="ask",
            risk_level="high",
            reasons=[f"SkillHUB {action} writes this agent's skill extension directory"],
            normalized_arguments=normalized,
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="deny",
        risk_level="high",
        reasons=[f"unknown SkillHUB action: {action}"],
    ).model_dump(mode="json")


def _normalized_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip().lower()
    if action not in {"status", "search", "install", "remove"}:
        raise ValueError(f"unsupported SkillHUB action: {action}")
    if action == "status":
        return {"action": action}
    if action == "search":
        query = normalize_skillhub_search_query(str(arguments.get("query") or ""))
        return {"action": action, "query": query}
    skill = str(arguments.get("skill") or "").strip()
    if not skill:
        raise ValueError(f"SkillHUB {action} requires skill")
    return {"action": action, "skill": skill}
