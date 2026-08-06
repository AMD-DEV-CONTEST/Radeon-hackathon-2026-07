from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


ASK_USER_TOOL_ID = "ask_user"


def get_ask_user_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=ASK_USER_TOOL_ID,
            description=(
                "Pauses the current delegated task and asks one concrete question that genuinely blocks "
                "further work. Call it immediately in the same model response that decides user input is "
                "required, and only when the answer cannot be determined from existing task information, "
                "files, or tool results. Provide a small set of mutually exclusive options or allow free text. "
                "The task resumes from the current checkpoint after the user answers."
            ),
            entrypoint="agent_factory.tooling.builtins.ask_user.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={"runtime_execution_config": "runtime_execution_config"},
            risk_level="low",
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "question": {"type": "string", "minLength": 1},
            "title": {"type": "string", "minLength": 1},
            "options": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "value": {"type": "string", "minLength": 1},
                        "label": {"type": "string", "minLength": 1},
                        "description": {"type": "string"},
                    },
                    "required": ["value", "label"],
                },
            },
            "allow_free_text": {"type": "boolean", "default": True},
        },
        "required": ["question"],
    }
