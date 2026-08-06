from __future__ import annotations

from typing import Any

from agent_factory.tooling.skills.skill_tool_protocol import (
    current_system_string,
    registry_from_resources,
    repair_resource_mode,
    required_string,
    resource_mode,
    resource_paths,
    skill_error_facts,
    skill_error_guidance,
)
from agent_factory.tooling.spec import ToolRiskResult


def evaluate_skill_tool_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    resources = dict(context.get("resources") or {})
    try:
        registry = registry_from_resources(resources)
        action = str(arguments.get("action") or "").strip()
        if action == "list":
            return ToolRiskResult(action="allow", risk_level="low").model_dump(mode="json")
        if action == "search":
            required_string(arguments, "query")
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill search exposes enabled skill metadata only"],
            ).model_dump(mode="json")
        if action == "list_loaded":
            current_system = current_system_string(arguments, resources)
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill loaded-state inspection exposes gateway state only"],
                facts={"current_system": current_system},
            ).model_dump(mode="json")
        name = required_string(arguments, "name")
        registry.get(name)
        if action == "describe":
            current_system = current_system_string(arguments, resources)
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill describe exposes metadata and resource index only"],
                facts={"skill": name, "current_system": current_system},
            ).model_dump(mode="json")
        if action == "load":
            current_system = current_system_string(arguments, resources)
            reason = required_string(arguments, "reason")
            registry.load(name, current_system=current_system, reason=reason)
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill load exposes one enabled SKILL.md body to the model for the current manufacturing context"],
                facts={"skill": name, "current_system": current_system, "reason": reason},
            ).model_dump(mode="json")
        if action == "read_resource":
            current_system = current_system_string(arguments, resources)
            path = required_string(arguments, "path")
            mode = resource_mode(arguments.get("mode"))
            pointer = str(arguments.get("pointer") or "").strip()
            reason = str(arguments.get("reason") or "").strip()
            registry.read_resource(name, path, current_system=current_system, mode=mode, pointer=pointer, reason=reason)
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill resource read is restricted to enabled skill resources or script sources"],
                facts={"skill": name, "path": path, "mode": mode, "current_system": current_system},
            ).model_dump(mode="json")
        if action == "read_repair_resources":
            current_system = current_system_string(arguments, resources)
            paths = resource_paths(arguments.get("paths"))
            registry.describe(name, current_system=current_system)
            for path in paths:
                registry.read_resource(
                    name,
                    path,
                    current_system=current_system,
                    mode=repair_resource_mode(path),
                    reason="validator recommended repair resources",
                )
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill repair resource bundle is restricted to enabled skill resources"],
                facts={"skill": name, "paths": paths, "current_system": current_system},
            ).model_dump(mode="json")
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=["skill action must be one of: list, search, describe, load, list_loaded, read_resource, read_repair_resources"],
        ).model_dump(mode="json")
    except Exception as exc:
        guidance = skill_error_guidance(arguments, exc)
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=[
                f"skill request is invalid: {type(exc).__name__}: {exc}",
                guidance,
            ],
            facts=skill_error_facts(arguments, exc),
        ).model_dump(mode="json")
