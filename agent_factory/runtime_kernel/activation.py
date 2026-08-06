from __future__ import annotations

from typing import Any


PLAN_AND_EXECUTE_ACTIVATION_FIELDS = ("workflow_goal", "start_when", "ask_when_missing")


def normalize_plan_and_execute_activation(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    activation: dict[str, str] = {}
    for key in PLAN_AND_EXECUTE_ACTIVATION_FIELDS:
        text = str(value.get(key) or "").strip()
        if not text:
            return {}
        activation[key] = text
    return activation
