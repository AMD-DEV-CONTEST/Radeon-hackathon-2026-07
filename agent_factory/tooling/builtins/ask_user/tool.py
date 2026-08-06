from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from agent_factory.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    _require_delegated_run(resources)
    question = str(arguments.get("question") or "").strip()
    if not question:
        raise ValueError("question is required")
    options = _options(arguments.get("options"))
    answer = interrupt(
        {
            "type": "ask_user",
            "presentation": "assistant_dialogue",
            "resume_kind": "answer",
            "title": str(arguments.get("title") or "The child Agent needs your answer").strip(),
            "message": question,
            "options": options,
            "allow_free_text": bool(arguments.get("allow_free_text", True)),
        }
    )
    answer_payload = dict(answer) if isinstance(answer, dict) else {"answer": str(answer or "")}
    return tool_envelope(
        {"status": "answered", **answer_payload},
        summary="The user answered; continue the current delegated task.",
    )


def _require_delegated_run(resources: dict[str, Any]) -> None:
    execution = resources.get("runtime_execution_config")
    user_config = execution.get("user_config") if isinstance(execution, dict) else None
    context = user_config.get("delegation_context") if isinstance(user_config, dict) else None
    if not isinstance(context, dict):
        raise ValueError("ask_user is only available in a delegated child-Agent run")
    if not str(context.get("task_id") or "").strip() or not str(context.get("parent_session_id") or "").strip():
        raise ValueError("ask_user requires an active delegated background task")


def _options(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "value": str(item.get("value") or "").strip(),
            "label": str(item.get("label") or "").strip(),
            **(
                {"description": description}
                if (description := str(item.get("description") or "").strip())
                else {}
            ),
        }
        for item in value
        if isinstance(item, dict)
        and str(item.get("value") or "").strip()
        and str(item.get("label") or "").strip()
    ]
