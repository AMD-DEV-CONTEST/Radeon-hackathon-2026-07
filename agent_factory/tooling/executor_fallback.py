from __future__ import annotations

from typing import Any

from agent_factory.tooling.spec import ToolRiskResult


EXECUTOR_FALLBACK_REASON_FIELD = "fallback_reason"
EXECUTOR_FALLBACK_TOOL_IDS = frozenset({"shell"})


def executor_fallback_risk(arguments: dict[str, Any], context: dict[str, Any]) -> ToolRiskResult | None:
    tool_id = str(context.get("tool_id") or "").strip()
    if tool_id not in EXECUTOR_FALLBACK_TOOL_IDS:
        return None
    tool_call = context.get("tool_call")
    origin_node_id = str(tool_call.get("origin_node_id") or "").strip() if isinstance(tool_call, dict) else ""
    if origin_node_id != "executor":
        return None
    reason = str(arguments.get(EXECUTOR_FALLBACK_REASON_FIELD) or "").strip()
    facts = {
        "origin_node_id": origin_node_id,
        "fallback_reason": reason,
        "required_argument": EXECUTOR_FALLBACK_REASON_FIELD,
    }
    if not reason:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[
                (
                    f"executor may call {tool_id} only when available package/runtime tools cannot complete "
                    f"the current plan step; include {EXECUTOR_FALLBACK_REASON_FIELD} explaining that gap"
                )
            ],
            facts=facts,
        )
    return ToolRiskResult(
        action="ask",
        risk_level="high",
        reasons=[
            (
                f"executor fallback tool {tool_id} requested because package/runtime tools were declared insufficient: "
                f"{reason}"
            )
        ],
        facts=facts,
    )
