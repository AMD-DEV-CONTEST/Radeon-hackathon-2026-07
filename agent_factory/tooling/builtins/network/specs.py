from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_NETWORK_RESOURCE = {"network": "network"}


NETWORK_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        id="web_fetch",
        description="Fetches content from a specified URL.",
        entrypoint="agent_factory.tooling.builtins.network.web_fetch:run",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to request."},
                "method": {"type": "string", "enum": ["GET", "HEAD"], "default": "GET"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "timeout_seconds": {"type": "integer", "minimum": 1},
                "max_bytes": {"type": "integer", "minimum": 1},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "url": _STRING,
                "status_code": _INTEGER,
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "content": _STRING,
                "truncated": _BOOLEAN,
            },
            "required": ["url", "status_code", "headers", "content", "truncated"],
            "additionalProperties": False,
        },
        resources=_NETWORK_RESOURCE,
        risk_level="medium",
        concurrent=True,
    ),
    ToolSpec(
        id="web_search",
        description="Runs a web search with optional domain filtering.",
        entrypoint="agent_factory.tooling.builtins.network.web_search:run",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "domains": {"type": "array", "items": _STRING},
                "max_results": {"type": "integer", "minimum": 1},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": _STRING,
                            "url": _STRING,
                            "snippet": _STRING,
                        },
                        "required": ["title", "url", "snippet"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["results"],
            "additionalProperties": False,
        },
        resources=_NETWORK_RESOURCE,
        risk_level="medium",
        concurrent=True,
    ),
]


def get_network_tool_specs() -> list[ToolSpec]:
    return [tool.model_copy(deep=True) for tool in NETWORK_TOOL_SPECS]
