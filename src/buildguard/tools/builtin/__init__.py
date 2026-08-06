"""Built-in read-only tools."""

from collections.abc import Callable
from typing import Any

from buildguard.config import Settings
from buildguard.security.path_guard import PathGuard
from buildguard.tools.builtin.file_tools import register_file_tools
from buildguard.tools.builtin.history_tools import register_history_tools
from buildguard.tools.builtin.system_tools import register_system_tools
from buildguard.tools.registry import ToolRegistry

HistoryProvider = Callable[[str | None, int], list[dict[str, Any]]]


def create_builtin_registry(
    settings: Settings, history_provider: HistoryProvider
) -> ToolRegistry:
    """Build the fixed startup registry from validated local configuration."""
    registry = ToolRegistry()
    uploads = (settings.app.workspace_dir / "uploads").resolve()
    uploads.mkdir(parents=True, exist_ok=True)
    register_file_tools(
        registry,
        PathGuard([uploads]),
        uploads,
        max_items=settings.app.tools.inspection_image_max_items,
        timeout_seconds=settings.app.tools.default_timeout_seconds,
    )
    register_history_tools(
        registry,
        history_provider,
        timeout_seconds=settings.app.tools.default_timeout_seconds,
    )
    register_system_tools(
        registry, timeout_seconds=settings.app.tools.default_timeout_seconds
    )
    return registry


__all__ = [
    "create_builtin_registry",
    "register_file_tools",
    "register_history_tools",
    "register_system_tools",
]
