"""Local runtime status tool."""

import os
import platform
import sys

import psutil

from buildguard.tools.base import ToolDefinition
from buildguard.tools.registry import ToolRegistry
from buildguard.tools.schemas import RuntimeStatusInput, RuntimeStatusOutput


def register_system_tools(registry: ToolRegistry, *, timeout_seconds: float = 5) -> None:
    def runtime_status(raw: object) -> RuntimeStatusOutput:
        request = RuntimeStatusInput.model_validate(raw)
        if not request.include_process:
            return RuntimeStatusOutput(
                operating_system=platform.system(),
                python_version=sys.version.split()[0],
            )
        process = psutil.Process(os.getpid())
        return RuntimeStatusOutput(
            operating_system=platform.system(),
            python_version=sys.version.split()[0],
            cpu_percent=psutil.cpu_percent(interval=None),
            process_memory_mb=process.memory_info().rss / (1024 * 1024),
        )

    registry.register(
        ToolDefinition(
            name="get_runtime_status",
            description="Read local operating system and current process resource status.",
            input_schema=RuntimeStatusInput,
            output_schema=RuntimeStatusOutput,
            permission="auto",
            read_only=True,
            timeout_seconds=timeout_seconds,
            category="system",
        ),
        runtime_status,
    )

