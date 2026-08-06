from __future__ import annotations

import uuid
from typing import Any, Callable

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from web_frontend.backend.runtime_bridge import RuntimeBridge


async def resource_command(
    runtime_bridge: RuntimeBridge,
    command_type: str,
    payload: dict[str, Any],
    event_types: set[str],
    *,
    timeout_seconds: float | None = 30.0,
    event_filter: Callable[[dict[str, Any]], bool] | None = None,
    request_id_value: str | None = None,
) -> dict[str, Any]:
    return await send_and_wait(
        runtime_bridge,
        command_type,
        payload,
        event_types,
        timeout_seconds=timeout_seconds,
        event_filter=event_filter,
        request_id_value=request_id_value,
    )


async def send_and_wait(
    runtime_bridge: RuntimeBridge,
    command_type: str,
    payload: dict[str, Any],
    event_types: set[str],
    *,
    timeout_seconds: float | None = 30.0,
    event_filter: Callable[[dict[str, Any]], bool] | None = None,
    request_id_value: str | None = None,
) -> dict[str, Any]:
    command = FactoryFrontendCommand(type=command_type, request_id=request_id_value or request_id(), payload=payload)
    return await runtime_bridge.send_and_wait(
        command,
        event_types=event_types,
        timeout_seconds=timeout_seconds,
        event_filter=event_filter,
    )


def request_id() -> str:
    return f"http-{uuid.uuid4().hex}"


def optional_package(package_id: str | None) -> dict[str, str]:
    return {"package_id": package_id} if package_id else {}


def optional_resource_mode(value: Any) -> dict[str, str]:
    resource_mode = str(value or "").strip()
    return {"resource_mode": resource_mode} if resource_mode else {}
