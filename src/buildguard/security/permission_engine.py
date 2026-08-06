"""Tool-level permission decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from buildguard.security.confirmation import ConfirmationManager
from buildguard.tools.base import ToolDefinition
from buildguard.tools.schemas import PermissionCheck, ToolExecutionRequest

CONFIRMATION_OPERATIONS = {
    "start_camera",
    "stop_camera",
    "write_report",
    "overwrite_report",
    "clear_memory",
}


class PermissionEngine:
    def __init__(self, confirmations: ConfirmationManager) -> None:
        self.confirmations = confirmations

    @staticmethod
    def _access_paths(
        arguments: dict[str, Any], definition: ToolDefinition
    ) -> list[Path]:
        paths: list[Path] = []
        for key in ("path", "directory", "output_path"):
            value = arguments.get(key)
            if isinstance(value, (str, Path)):
                path = Path(value)
                if not path.is_absolute() and definition.allowed_roots:
                    path = definition.allowed_roots[0] / path
                paths.append(path)
        return paths

    def check(
        self, definition: ToolDefinition, request: ToolExecutionRequest
    ) -> PermissionCheck:
        if definition.permission == "deny":
            return PermissionCheck(decision="deny", reason="Tool policy is deny")
        needs_confirmation = (
            definition.permission == "confirm"
            or definition.name in CONFIRMATION_OPERATIONS
            or (
                definition.name == "list_inspection_images"
                and bool(request.arguments.get("recursive"))
            )
        )
        if not needs_confirmation:
            return PermissionCheck(decision="allow", reason="Tool policy allows automatic execution")
        if request.confirmation_id is not None:
            try:
                confirmation = self.confirmations.get(request.confirmation_id)
            except KeyError:
                return PermissionCheck(decision="deny", reason="Confirmation does not exist")
            if confirmation.tool_name != definition.name:
                return PermissionCheck(decision="deny", reason="Confirmation is for another tool")
            if confirmation.status == "approved":
                return PermissionCheck(decision="allow", reason="User approved the operation")
            return PermissionCheck(
                decision="deny", reason=f"Confirmation status is {confirmation.status}"
            )
        confirmation = self.confirmations.create(
            definition.name,
            request.arguments,
            self._access_paths(request.arguments, definition),
            "This operation may access multiple files, a device, memory, or modify local data.",
        )
        return PermissionCheck(
            decision="confirm",
            reason="Explicit user confirmation is required",
            confirmation=confirmation,
        )
