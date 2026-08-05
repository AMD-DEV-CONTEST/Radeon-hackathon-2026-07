from __future__ import annotations

from typing import Any, Callable

from langchain_core.tools import StructuredTool

from privateops.models import ToolResult
from privateops.tools import ToolRegistry


TOOL_DESCRIPTIONS = {
    "workspace_inventory": "List files inside the configured private workspace without leaving its boundary.",
    "search_text": "Search supported text files inside the configured private workspace.",
    "submission_readiness": "Check required competition project artifacts inside the private workspace.",
    "run_tests": "Run one exact allow-listed local test command inside the private workspace.",
    "startup_inventory": "Inspect fixed Windows startup registry locations and Startup folders without changing them.",
    "process_inventory": "Inspect bounded running-process metadata without reading command lines.",
    "service_inventory": "Inspect Windows service state and start mode without changing services.",
    "scheduled_task_inventory": "Inspect Windows scheduled task names, states, and trigger types without changing tasks.",
    "system_overview": "Inspect Windows, CPU, memory, GPU, and fixed-disk facts.",
    "network_listener_inventory": "Inspect local listening TCP ports and owning processes without reading traffic.",
    "security_status": "Inspect Microsoft Defender and Windows Firewall posture without changing settings.",
}


class LangChainToolAdapter:
    framework_name = "LangChain Core"

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.tools = {
            name: StructuredTool.from_function(
                func=self._runner(name),
                name=name,
                description=description,
            )
            for name, description in TOOL_DESCRIPTIONS.items()
        }

    def _runner(self, name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def run(arguments: dict[str, Any]) -> dict[str, Any]:
            return self.registry.execute(name, arguments).to_dict()

        return run

    def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return self.registry.execute(name, arguments)
        payload = tool.invoke({"arguments": arguments})
        return ToolResult(
            name=str(payload["name"]),
            status=str(payload["status"]),
            summary=str(payload["summary"]),
            output=dict(payload.get("output", {})),
        )
