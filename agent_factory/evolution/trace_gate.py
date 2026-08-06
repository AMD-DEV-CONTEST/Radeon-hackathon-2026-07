from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from agent_factory.models import get_task_model
from agent_factory.models.content import strip_internal_snapshot_blocks


class TraceRelevanceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevance: Literal["high", "medium", "low"] = "low"
    provide_trace: bool = False
    reason: str = ""
    gate_error: str | None = None


def decide_trace_relevance(*, user_goal: str, error_pack: dict[str, Any]) -> TraceRelevanceDecision:
    model = get_task_model()
    if model is None:
        return TraceRelevanceDecision(
            relevance="low",
            provide_trace=False,
            reason="task model is not configured; trace details were withheld by default",
            gate_error="task_model_not_configured",
        )
    prompt = {
        "user_goal": user_goal,
        "trace_error_summary": _compact_error_pack(error_pack),
        "decision_policy": {
            "high": "The user goal directly asks to fix the same failing node/tool/model/runtime area.",
            "medium": "The trace failure could block validation, probing, or runtime readiness for the user goal.",
            "low": "The trace failure is unrelated background noise and should not be shown to the main evolution model.",
        },
    }
    messages = [
        SystemMessage(
            content=(
                "You are a relevance gate for AgentPackage evolution. "
                "Decide whether failed trace error details should be provided to the main evolution model. "
                "The user goal is primary. Return JSON only with keys relevance, provide_trace, reason. "
                "Set provide_trace=true only for high or medium relevance."
            )
        ),
        HumanMessage(content=json.dumps(prompt, ensure_ascii=False, indent=2)),
    ]
    try:
        response = model.invoke(messages)
        text = strip_internal_snapshot_blocks(str(getattr(response, "content", response) or "")).strip()
        payload = _json_object_from_text(text)
        decision = TraceRelevanceDecision.model_validate(payload)
        return decision.model_copy(update={"provide_trace": decision.relevance in {"high", "medium"} and decision.provide_trace})
    except Exception as exc:
        return TraceRelevanceDecision(
            relevance="low",
            provide_trace=False,
            reason="task model relevance gate failed; trace details were withheld by default",
            gate_error=f"{type(exc).__name__}: {exc}",
        )


def _compact_error_pack(error_pack: dict[str, Any]) -> dict[str, Any]:
    error_chain = error_pack.get("error_chain") if isinstance(error_pack.get("error_chain"), list) else []
    compact_errors: list[dict[str, Any]] = []
    for item in error_chain[-3:]:
        if not isinstance(item, dict):
            continue
        compact_errors.append(
            {
                "event_type": item.get("event_type"),
                "node_id": item.get("node_id"),
                "span_kind": item.get("span_kind"),
                "status": item.get("status"),
                "message": item.get("message"),
                "error_summary": item.get("error_summary"),
                "payload": _small_payload(item.get("payload")),
            }
        )
    return {
        "status": error_pack.get("status"),
        "failed_node": error_pack.get("failed_node"),
        "failure_category": error_pack.get("failure_category"),
        "suspected_root_causes": error_pack.get("suspected_root_causes"),
        "repair_targets": error_pack.get("repair_targets"),
        "recent_errors": compact_errors,
    }


def _small_payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    result = {}
    for key in ("where", "error", "message", "model", "operation", "tool_id", "status"):
        if key in value:
            result[key] = value[key]
    return result


def _json_object_from_text(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("trace relevance gate returned non-object JSON")
    return value
