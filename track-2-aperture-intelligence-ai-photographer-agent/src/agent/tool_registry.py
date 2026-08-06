"""Neutral tool registry with permission checks, timing, and audit records."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from src.agent.permissions import PermissionDenied, PermissionPolicy


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    device: str
    permissions: tuple[str, ...] = ()


DEFAULT_TOOLS = (
    ToolDefinition(
        "intent_router",
        "Route the user request to shooting, editing, or hybrid planning.",
        "CPU",
    ),
    ToolDefinition(
        "vision_analyzer",
        "Understand the image and ground people, props, actions, and composition.",
        "AMD Radeon GPU / ROCm HIP",
        ("read_uploaded_image", "gpu_inference"),
    ),
    ToolDefinition(
        "composition_checker",
        "Check whether visual evidence is sufficiently actionable.",
        "CPU",
    ),
    ToolDefinition(
        "photography_planner",
        "Create the photographer and subject action sequence.",
        "CPU",
    ),
    ToolDefinition(
        "plan_critic",
        "Reject incomplete, unsafe, or internally inconsistent plans.",
        "CPU",
    ),
    ToolDefinition(
        "pose_analyzer",
        "Validate structured body, hands, gaze, and photographer directions.",
        "CPU",
    ),
    ToolDefinition(
        "plan_refiner",
        "Perform one bounded deterministic repair using critic findings.",
        "CPU",
    ),
    ToolDefinition(
        "pose_card_renderer",
        "Deterministically render a photography execution card from local segmentation.",
        "AMD Radeon GPU / ROCm HIP",
        (
            "read_uploaded_image",
            "gpu_inference",
            "write_temporary_result",
        ),
    ),
)


class ToolRegistry:
    """Invoke registered tools without coupling the Agent to an external framework."""

    def __init__(
        self,
        policy: PermissionPolicy | None = None,
        definitions: tuple[ToolDefinition, ...] = DEFAULT_TOOLS,
    ) -> None:
        self.policy = policy or PermissionPolicy()
        self._definitions = {tool.name: tool for tool in definitions}
        self.begin_run()

    def begin_run(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.permission_audit: list[dict[str, str]] = []

    def manifest(self) -> list[dict[str, Any]]:
        return [
            {
                **asdict(tool),
                "permissions": list(tool.permissions),
            }
            for tool in self._definitions.values()
        ]

    def invoke(
        self,
        name: str,
        handler: Callable[[], Any],
        *,
        input_summary: dict[str, Any] | None = None,
        output_summary: Callable[[Any], Any] | None = None,
    ) -> Any:
        if name not in self._definitions:
            raise KeyError(f"Unregistered Agent tool: {name}")
        definition = self._definitions[name]
        started = time.perf_counter()
        record: dict[str, Any] = {
            "tool": name,
            "device": definition.device,
            "status": "running",
            "input": input_summary or {},
        }
        self.calls.append(record)
        try:
            audit = self.policy.authorize(name, definition.permissions)
            self.permission_audit.extend(audit)
            result = handler()
            record["status"] = "completed"
            record["output"] = (
                output_summary(result) if output_summary else {"available": True}
            )
            return result
        except PermissionDenied as exc:
            self.permission_audit.extend(exc.audit)
            record["status"] = "denied"
            raise
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["seconds"] = round(time.perf_counter() - started, 3)
