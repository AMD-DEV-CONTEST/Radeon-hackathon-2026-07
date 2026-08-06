from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .errors import AgentError


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_deployments",
            "description": "Read recent deployment changes for one service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "since": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["service", "since", "limit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_metrics",
            "description": "Read a service metric over a bounded time range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "metric": {"type": "string", "enum": ["latency_p95", "http_5xx_rate", "db_pool_waiters"]},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "aggregation": {"type": "string", "enum": ["max", "avg", "p95"]},
                },
                "required": ["service", "metric", "start", "end", "aggregation"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_logs",
            "description": "Read sanitized application logs for one service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "query": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["service", "query", "start", "end", "limit"],
                "additionalProperties": False,
            },
        },
    },
]


DEFAULT_ARGUMENTS: dict[str, dict[str, Any]] = {
    "get_deployments": {"service": "checkout-api", "since": "2026-07-22T13:45:00Z", "limit": 10},
    "query_metrics": {
        "service": "checkout-api",
        "metric": "db_pool_waiters",
        "start": "2026-07-22T13:55:00Z",
        "end": "2026-07-22T14:15:00Z",
        "aggregation": "max",
    },
    "search_logs": {
        "service": "checkout-api",
        "query": "database connection pool timeout pricing",
        "start": "2026-07-22T13:55:00Z",
        "end": "2026-07-22T14:15:00Z",
        "limit": 20,
    },
}


@dataclass(frozen=True)
class ToolResult:
    name: str
    arguments: dict[str, Any]
    records: tuple[dict[str, str], ...]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[[dict[str, Any]], tuple[dict[str, str], ...]]] = {
            "get_deployments": self._get_deployments,
            "query_metrics": self._query_metrics,
            "search_logs": self._search_logs,
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return TOOL_SCHEMAS

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise AgentError(f"unknown tool: {name}", "unknown_tool", 400)
        self._validate(name, arguments)
        return ToolResult(name, dict(arguments), tool(arguments))

    @staticmethod
    def _validate(name: str, arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise AgentError("tool arguments must be an object", "invalid_tool_arguments", 400)
        if arguments.get("service") != "checkout-api":
            raise AgentError("demo tools only allow checkout-api", "invalid_tool_arguments", 400)
        expected = set(DEFAULT_ARGUMENTS[name])
        if set(arguments) != expected:
            raise AgentError("tool arguments do not match the allowlisted schema", "invalid_tool_arguments", 400)
        if any(not isinstance(arguments[key], str) or not arguments[key] or len(arguments[key]) > 500 for key in expected if key != "limit"):
            raise AgentError("tool string arguments must be non-empty and bounded", "invalid_tool_arguments", 400)
        if "limit" in arguments and (not isinstance(arguments["limit"], int) or isinstance(arguments["limit"], bool)):
            raise AgentError("tool limit must be an integer", "invalid_tool_arguments", 400)
        if name == "get_deployments" and not 1 <= arguments["limit"] <= 20:
            raise AgentError("deployment limit must be between 1 and 20", "invalid_tool_arguments", 400)
        if name == "query_metrics":
            if arguments["metric"] not in {"latency_p95", "http_5xx_rate", "db_pool_waiters"}:
                raise AgentError("unsupported metric", "invalid_tool_arguments", 400)
            if arguments["aggregation"] not in {"max", "avg", "p95"}:
                raise AgentError("unsupported aggregation", "invalid_tool_arguments", 400)
        if name == "search_logs" and not 1 <= arguments["limit"] <= 50:
            raise AgentError("log limit must be between 1 and 50", "invalid_tool_arguments", 400)

    @staticmethod
    def _get_deployments(arguments: dict[str, Any]) -> tuple[dict[str, str], ...]:
        return (
            {
                "timestamp": "2026-07-22T14:02:00Z",
                "source": "deployment-adapter",
                "content": "checkout-api 2026.07.22-rc3 canary rollout reached 10%; previous version was 2026.07.19-rc1.",
            },
            {
                "timestamp": "2026-07-22T14:04:00Z",
                "source": "deployment-adapter",
                "content": "The rc3 release enabled the new pricing lookup path; no infrastructure configuration changed.",
            },
        )[: arguments["limit"]]

    @staticmethod
    def _query_metrics(arguments: dict[str, Any]) -> tuple[dict[str, str], ...]:
        metric = arguments["metric"]
        records = {
            "db_pool_waiters": (
                "Database pool waiters increased from 2 to 137 after the rc3 canary; active connections remained at the limit of 50.",
                "Postgres CPU remained below 65%, indicating application-side connection contention rather than database CPU exhaustion.",
            ),
            "latency_p95": ("Checkout p95 latency increased from 420 ms to 4.8 s after the rc3 canary.",),
            "http_5xx_rate": ("Checkout HTTP 5xx rate increased from 0.3% to 18% after the rc3 canary.",),
        }
        return tuple(
            {"timestamp": f"2026-07-22T14:{6 + index:02d}:00Z", "source": "metrics-adapter", "content": content}
            for index, content in enumerate(records[metric])
        )

    @staticmethod
    def _search_logs(arguments: dict[str, Any]) -> tuple[dict[str, str], ...]:
        records = (
            {
                "timestamp": "2026-07-22T14:07:12Z",
                "source": "logs-adapter",
                "content": "checkout-api pricing lookup failed: database connection pool timeout after 2000 ms; active=50 idle=0 waiting=137.",
            },
            {
                "timestamp": "2026-07-22T14:08:03Z",
                "source": "logs-adapter",
                "content": "Requests using the legacy pricing path completed normally; failures correlate with rc3 pricing lookup queries.",
            },
        )
        return records[: arguments["limit"]]
