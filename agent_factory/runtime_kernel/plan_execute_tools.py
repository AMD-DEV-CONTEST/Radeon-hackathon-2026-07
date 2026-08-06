from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.planning import RUNTIME_PLAN_TOOL_ID


PLAN_EXECUTE_PLANNER_NODE_ID = "planner"
PLAN_EXECUTE_EXECUTOR_NODE_ID = "executor"
PLAN_EXECUTE_CASUAL_NODE_ID = "casual_react"
PLAN_EXECUTE_FINAL_NODE_ID = "final_answer"
PLAN_EXECUTE_NODE_IDS = frozenset(
    {
        PLAN_EXECUTE_PLANNER_NODE_ID,
        PLAN_EXECUTE_EXECUTOR_NODE_ID,
        PLAN_EXECUTE_CASUAL_NODE_ID,
        PLAN_EXECUTE_FINAL_NODE_ID,
    }
)


def plan_and_execute_model_tool_ids(
    *,
    node_id: str,
    node_bindings: list[dict[str, Any]],
    all_bindings: list[dict[str, Any]],
    registry: Any,
    extra_tool_ids: list[str] | None = None,
) -> list[str]:
    node_tool_ids = tool_access_ids(node_bindings)
    runtime_tool_ids = extra_tool_ids or []
    if node_id == PLAN_EXECUTE_PLANNER_NODE_ID:
        return node_tool_ids
    if node_id == PLAN_EXECUTE_EXECUTOR_NODE_ID:
        return merge_tool_ids([*node_tool_ids, *runtime_tool_ids, *system_tool_ids(registry)])
    if node_id == PLAN_EXECUTE_CASUAL_NODE_ID:
        return without_runtime_plan(merge_tool_ids([*node_tool_ids, *runtime_tool_ids, *system_tool_ids(registry)]))
    if node_id == PLAN_EXECUTE_FINAL_NODE_ID:
        return plan_and_execute_delivery_tool_ids(
            node_bindings=node_bindings,
            all_bindings=all_bindings,
            registry=registry,
            extra_tool_ids=runtime_tool_ids,
        )
    return node_tool_ids


def plan_and_execute_delegated_tool_ids(
    *,
    origin_node_id: str,
    all_bindings: list[dict[str, Any]],
    registry: Any,
    extra_tool_ids: list[str] | None = None,
) -> list[str]:
    runtime_tool_ids = extra_tool_ids or []
    if origin_node_id == PLAN_EXECUTE_PLANNER_NODE_ID:
        return []
    if origin_node_id in {PLAN_EXECUTE_EXECUTOR_NODE_ID, PLAN_EXECUTE_CASUAL_NODE_ID}:
        return without_runtime_plan(
            merge_tool_ids(
                [
                    *tool_access_ids_for_node(all_bindings, node_id=origin_node_id),
                    *runtime_tool_ids,
                    *system_tool_ids(registry),
                ]
            )
        )
    if origin_node_id == PLAN_EXECUTE_FINAL_NODE_ID:
        return plan_and_execute_delivery_tool_ids(
            node_bindings=tool_access_bindings_for_node(all_bindings, node_id=PLAN_EXECUTE_FINAL_NODE_ID),
            all_bindings=all_bindings,
            registry=registry,
            extra_tool_ids=runtime_tool_ids,
        )
    return []


def plan_and_execute_runtime_plan_tool_ids(*, origin_node_id: str, all_bindings: list[dict[str, Any]]) -> list[str]:
    allowed_tool_ids = tool_access_ids_for_node(all_bindings, node_id=origin_node_id)
    if origin_node_id in {PLAN_EXECUTE_PLANNER_NODE_ID, PLAN_EXECUTE_EXECUTOR_NODE_ID}:
        return allowed_tool_ids
    return without_runtime_plan(allowed_tool_ids)


def plan_and_execute_delivery_tool_ids(
    *,
    node_bindings: list[dict[str, Any]],
    all_bindings: list[dict[str, Any]],
    registry: Any,
    extra_tool_ids: list[str] | None = None,
) -> list[str]:
    final_tool_ids = tool_access_ids(node_bindings)
    source_tool_ids = final_tool_ids or tool_access_ids_for_node(all_bindings, node_id=PLAN_EXECUTE_EXECUTOR_NODE_ID)
    return without_runtime_plan(merge_tool_ids([*source_tool_ids, *(extra_tool_ids or []), *system_tool_ids(registry)]))


def tool_access_bindings_for_node(bindings: list[dict[str, Any]], *, node_id: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for binding in bindings:
        if binding.get("binding_type") != "tool_access":
            continue
        target = dict(binding.get("target") or {})
        if str(target.get("node_id") or "") == node_id:
            selected.append(binding)
    return selected


def tool_access_ids(bindings: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for binding in bindings:
        if binding.get("binding_type") != "tool_access":
            continue
        payload = dict(binding.get("payload") or {})
        for item in payload.get("allowed_tool_ids", []) or []:
            tool_id = str(item)
            if tool_id and tool_id not in seen:
                ids.append(tool_id)
                seen.add(tool_id)
    return ids


def tool_access_ids_for_node(bindings: list[dict[str, Any]], *, node_id: str) -> list[str]:
    return tool_access_ids(tool_access_bindings_for_node(bindings, node_id=node_id))


def system_tool_ids(registry: Any) -> list[str]:
    if not hasattr(registry, "system_tool_ids"):
        return []
    return [str(item) for item in registry.system_tool_ids()]


def merge_tool_ids(tool_ids: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for tool_id in tool_ids:
        item = str(tool_id).strip()
        if item and item not in seen:
            items.append(item)
            seen.add(item)
    return items


def without_runtime_plan(tool_ids: list[str]) -> list[str]:
    return [tool_id for tool_id in tool_ids if tool_id != RUNTIME_PLAN_TOOL_ID]
