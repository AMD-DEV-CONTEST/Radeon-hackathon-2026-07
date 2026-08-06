from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from collections.abc import Callable

from agent_factory.file_lock import exclusive_file_lock
from agent_factory.tooling.skills.registry import SkillRegistry, SkillResourceFragmentNotFound
from agent_factory.tooling.skills.schema import SkillGatewayState


SKILL_ACTIONS = ("list", "search", "describe", "load", "list_loaded", "read_resource", "read_repair_resources")
SKILL_RESOURCE_KEY = "skills"
SKILL_GATEWAY_STATE_RESOURCE_KEY = "skill_gateway_state_path"
SKILL_TOOL_ID = "skill"


def registry_from_resources(resources: dict[str, Any]) -> SkillRegistry:
    payload = resources.get(SKILL_RESOURCE_KEY)
    if not isinstance(payload, dict):
        raise ValueError("skills runtime resource is missing")
    return SkillRegistry.from_resource_payload(payload)


def persist_registry(resources: dict[str, Any], registry: SkillRegistry) -> None:
    payload = resources.get(SKILL_RESOURCE_KEY)
    if not isinstance(payload, dict):
        raise ValueError("skills runtime resource is missing")
    payload.clear()
    payload.update(registry.to_resource_payload())
    state_path = gateway_state_path(resources)
    if state_path is not None:
        _atomic_write_json(state_path, registry.gateway_state.model_dump(mode="json"))


def gateway_state_path(resources: dict[str, Any]) -> Path | None:
    raw_state_path = resources.get(SKILL_GATEWAY_STATE_RESOURCE_KEY)
    if isinstance(raw_state_path, str) and raw_state_path.strip():
        return Path(raw_state_path).expanduser().resolve()
    return None


def run_with_gateway_state_lock(resources: dict[str, Any], callback: Callable[[SkillRegistry], dict[str, Any]]) -> dict[str, Any]:
    state_path = gateway_state_path(resources)
    if state_path is None:
        registry = registry_from_resources(resources)
        return callback(registry)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    with exclusive_file_lock(lock_path):
        registry = registry_from_resources(resources)
        if state_path.exists():
            registry.gateway_state = SkillGatewayState.model_validate_json(state_path.read_text(encoding="utf-8"))
        result = callback(registry)
        persist_registry(resources, registry)
        return result

def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def current_system_string(arguments: dict[str, Any], resources: dict[str, Any], key: str = "current_system") -> str:
    del resources
    return required_string(arguments, key)


def limit_value(value: Any) -> int:
    if value is None:
        return 20
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer")
    return max(1, min(50, value))


def resource_mode(value: Any) -> str:
    mode = str(value or "outline").strip()
    if mode not in {"outline", "fragment", "content"}:
        raise ValueError("mode must be one of: outline, fragment, content")
    return mode


def resource_paths(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("paths must be a non-empty list of skill resource paths")
    paths: list[str] = []
    for item in value:
        path = str(item or "").strip()
        if not path:
            raise ValueError("paths must not contain empty values")
        paths.append(path)
    return paths


def repair_resource_mode(path: str) -> str:
    if path.endswith(".schema.json"):
        return "outline"
    return "content"


def skill_error_guidance(arguments: dict[str, Any], exc: Exception) -> str:
    action = str(arguments.get("action") or "").strip()
    if action == "read_resource" and isinstance(exc, PermissionError):
        name = str(arguments.get("name") or "").strip()
        current_system = str(arguments.get("current_system") or "").strip()
        return (
            "Protocol violation: read_resource requires the same skill to be described or loaded first "
            f"for current_system={current_system!r}. Next call: "
            f"skill(action='describe', name={name!r}, current_system={current_system!r}), then retry read_resource."
        )
    if action == "read_resource" and isinstance(exc, SkillResourceFragmentNotFound):
        return (
            "Invalid resource fragment: the skill resource exists, but the requested JSON pointer is not present. "
            "Read the resource in outline mode or use one of the available top-level keys before retrying mode=fragment."
        )
    if action == "read_resource" and isinstance(exc, KeyError):
        return "Unknown skill resource path. Call describe for this skill and choose one of the returned resources or scripts."
    if action == "load" and isinstance(exc, PermissionError):
        name = str(arguments.get("name") or "").strip()
        current_system = str(arguments.get("current_system") or "").strip()
        return (
            "Loading a second primary skill requires describe for that skill first. "
            f"Next call: skill(action='describe', name={name!r}, current_system={current_system!r}); "
            "then retry load with a concrete reason if the described skill is still needed."
        )
    if action == "read_resource":
        return (
            "Read resource failed. Verify action, name, path, current_system, mode, and pointer. "
            "For schema resources, prefer mode=fragment with a JSON pointer; full schema content requires a reason. "
            "For scripts, use the exact scripts path listed by describe."
        )
    if action == "read_repair_resources":
        return "Read repair resources failed. Use recommended_skill and recommended_resources from the validator without renaming paths."
    return "Correct the skill action arguments according to the Skill Gateway protocol."


def skill_error_facts(arguments: dict[str, Any], exc: Exception) -> dict[str, Any]:
    facts = {
        "action": str(arguments.get("action") or ""),
        "name": str(arguments.get("name") or ""),
        "path": str(arguments.get("path") or ""),
        "mode": str(arguments.get("mode") or ""),
        "pointer": str(arguments.get("pointer") or ""),
        "current_system": str(arguments.get("current_system") or ""),
        "error_type": type(exc).__name__,
    }
    if isinstance(exc, SkillResourceFragmentNotFound):
        facts["error_category"] = "skill_resource_fragment_not_found"
        facts["available_top_level_keys"] = exc.available_keys
    elif isinstance(exc, KeyError):
        facts["error_category"] = "skill_resource_or_script_not_found"
    elif facts["action"] == "load" and isinstance(exc, PermissionError):
        facts["error_category"] = "second_primary_skill_requires_describe"
        facts["required_next_tool"] = "skill"
        facts["required_next_args"] = {
            "action": "describe",
            "name": facts["name"],
            "current_system": facts["current_system"],
        }
        facts["then_retry_load"] = True
    return facts
