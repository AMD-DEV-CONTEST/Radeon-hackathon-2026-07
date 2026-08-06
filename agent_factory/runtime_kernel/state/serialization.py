from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.state.schema import RuntimeState


def merge_state_patch(state: RuntimeState, patch: dict[str, Any]) -> RuntimeState:
    data = state.model_dump(mode="python")
    for key, value in patch.items():
        if key not in data:
            continue
        current = data[key]
        if isinstance(current, dict) and isinstance(value, dict):
            data[key] = {**current, **value}
        else:
            data[key] = value
    return RuntimeState.model_validate(data)
