from __future__ import annotations

from typing import Any

from agent_factory.background_task_policy import DELEGATED_CONTEXT_TOOL_IDS
from agent_factory.runtime_kernel.plan_execute_tools import merge_tool_ids
from agent_factory.runtime_kernel.state import RuntimeState


def runtime_excluded_tool_ids(state: RuntimeState) -> list[str]:
    user_config = state.runtime_config.user_config
    contextual_exclusions = [] if _delegation_context_enabled(user_config) else sorted(DELEGATED_CONTEXT_TOOL_IDS)
    return contextual_exclusions


def runtime_extra_allowed_tool_ids(state: RuntimeState) -> list[str]:
    user_config = state.runtime_config.user_config
    if not isinstance(user_config, dict):
        return []
    access = user_config.get("runtime_tool_access")
    if not isinstance(access, dict):
        return []
    ids = access.get("extra_allowed_tool_ids")
    if not isinstance(ids, list):
        return []
    allowed: list[str] = []
    for item in ids:
        tool_id = str(item or "").strip()
        if tool_id in DELEGATED_CONTEXT_TOOL_IDS and _delegation_context_enabled(user_config):
            allowed.append(tool_id)
    return merge_tool_ids(allowed)


def _delegation_context_enabled(user_config: Any) -> bool:
    if not isinstance(user_config, dict):
        return False
    context = user_config.get("delegation_context")
    if not isinstance(context, dict):
        return False
    return bool(
        str(context.get("parent_session_id") or "").strip()
        and str(context.get("task_id") or "").strip()
    )
