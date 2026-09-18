"""Allow-listed tools over synthetic incident fixtures."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping

from .schemas import ToolResult


ToolHandler = Callable[[Mapping[str, Any]], Dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    mutating: bool
    handler: ToolHandler


class DiagnosticEnvironment:
    def __init__(self, incident: Dict[str, Any]) -> None:
        self.incident = incident
        self.simulated_actions: List[Dict[str, Any]] = []

    @classmethod
    def from_json(cls, path: Path) -> "DiagnosticEnvironment":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @property
    def incident_id(self) -> str:
        return str(self.incident["incident_id"])

    @property
    def prompt(self) -> str:
        return str(self.incident["prompt"])

    @property
    def services(self) -> Mapping[str, Dict[str, Any]]:
        return self.incident.get("services", {})

    def inspect_service_health(
        self, arguments: Mapping[str, Any]
    ) -> Dict[str, Any]:
        service = str(arguments.get("service", "")).strip()
        if not service:
            raise ValueError("service is required")
        if service not in self.services:
            raise ValueError(f"unknown service: {service}")
        return {"service": service, **self.services[service]}

    def search_logs(self, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        service = str(arguments.get("service", "")).strip()
        query = str(arguments.get("query", "")).strip().lower()
        limit = min(max(int(arguments.get("limit", 10)), 1), 50)
        if not service:
            raise ValueError("service is required")
        entries = [
            entry
            for entry in self.incident.get("logs", [])
            if entry.get("service") == service
            and (
                not query
                or query in str(entry.get("message", "")).lower()
                or query in str(entry.get("level", "")).lower()
            )
        ]
        if not entries and query:
            entries = [
                entry
                for entry in self.incident.get("logs", [])
                if entry.get("service") == service
                and str(entry.get("level", "")).lower()
                in {"error", "warning", "warn"}
            ]
        return {
            "service": service,
            "query": query,
            "matches": entries[:limit],
        }

    def restart_service(self, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        service = str(arguments.get("service", "")).strip()
        if not service:
            raise ValueError("service is required")
        if service not in self.services:
            raise ValueError(f"unknown service: {service}")
        action = {
            "service": service,
            "action": "restart",
            "simulated": True,
            "result": "accepted",
        }
        self.simulated_actions.append(action)
        return action


class ToolBroker:
    def __init__(self, environment: DiagnosticEnvironment) -> None:
        self.environment = environment
        self._tools = {
            "inspect_service_health": ToolSpec(
                name="inspect_service_health",
                description="Read synthetic health metrics for a service",
                mutating=False,
                handler=environment.inspect_service_health,
            ),
            "search_logs": ToolSpec(
                name="search_logs",
                description="Search synthetic incident logs",
                mutating=False,
                handler=environment.search_logs,
            ),
            "restart_service": ToolSpec(
                name="restart_service",
                description="Simulate a service restart",
                mutating=True,
                handler=environment.restart_service,
            ),
        }

    @property
    def allowed_tools(self) -> List[str]:
        return sorted(self._tools)

    def execute(
        self,
        name: str,
        arguments: Mapping[str, Any],
        approved: bool = False,
    ) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(
                name=name,
                status="denied",
                output={
                    "error": "tool is not allow-listed",
                    "allowed_tools": self.allowed_tools,
                },
            )
        if spec.mutating and not approved:
            return ToolResult(
                name=name,
                status="approval_required",
                requires_approval=True,
                output={
                    "message": "Explicit human approval is required",
                    "arguments": dict(arguments),
                },
            )
        try:
            output = spec.handler(arguments)
        except (TypeError, ValueError) as error:
            return ToolResult(
                name=name,
                status="error",
                requires_approval=spec.mutating,
                output={"error": str(error)},
            )
        return ToolResult(
            name=name,
            status="completed",
            requires_approval=spec.mutating,
            output=output,
        )
