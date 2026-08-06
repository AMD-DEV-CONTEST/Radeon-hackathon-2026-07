from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Iterable, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_factory.tooling.providers.base import (
    RuntimeDependency,
    ToolProviderContext,
    ToolProviderResult,
    diagnostic,
)
from agent_factory.tooling.mcp_schema import normalize_mcp_schema
from agent_factory.tooling.schema_compiler import compile_json_schema
from agent_factory.tooling.spec import (
    ToolDescriptionContextConfig,
    ToolLoopPolicyConfig,
    ToolRiskEvaluatorConfig,
    ToolRiskLevel,
    ToolSpec,
)


SNAKE_CHARS = re.compile(r"[^a-z0-9_]+")


class MCPDiscoveredTool(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk_level: ToolRiskLevel | None = None
    risk_evaluator: ToolRiskEvaluatorConfig | None = None
    concurrent: bool | None = None


class MCPToolCatalogClient(Protocol):
    def list_tools(self) -> Iterable[MCPDiscoveredTool | dict[str, Any]]:
        ...


@dataclass(frozen=True, slots=True)
class PreparedMCPTool:
    spec: ToolSpec
    repairs: tuple[dict[str, Any], ...]


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    transport: Literal["stdio", "streamable_http", "sse"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    required: bool = False
    tool_id_prefix: str | None = None
    risk_level_default: ToolRiskLevel = "medium"
    concurrent_default: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0)
    tool_input_property_enums: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    tool_loop_policies: dict[str, ToolLoopPolicyConfig] = Field(default_factory=dict)
    tool_description_contexts: dict[str, ToolDescriptionContextConfig] = Field(default_factory=dict)

    @field_validator("tool_input_property_enums", mode="before")
    @classmethod
    def _validate_tool_input_property_enums(cls, value: Any) -> dict[str, dict[str, list[str]]]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("tool_input_property_enums must be an object")
        result: dict[str, dict[str, list[str]]] = {}
        for raw_tool_name, raw_properties in value.items():
            tool_name = str(raw_tool_name or "").strip()
            if not tool_name or not isinstance(raw_properties, dict):
                raise ValueError("tool_input_property_enums requires non-empty tool names and property maps")
            properties: dict[str, list[str]] = {}
            for raw_property_name, raw_allowed in raw_properties.items():
                property_name = str(raw_property_name or "").strip()
                if not property_name or not isinstance(raw_allowed, (list, tuple)):
                    raise ValueError("tool input enum overrides require non-empty property names and value arrays")
                allowed: list[str] = []
                for item in raw_allowed:
                    text = str(item or "").strip()
                    if text and text not in allowed:
                        allowed.append(text)
                if not allowed:
                    raise ValueError(f"tool input enum override must not be empty: {tool_name}.{property_name}")
                properties[property_name] = allowed
            result[tool_name] = properties
        return result

    @field_validator("tool_loop_policies", mode="before")
    @classmethod
    def _validate_tool_loop_policy_names(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, dict) or any(not str(name or "").strip() for name in value):
            raise ValueError("tool_loop_policies must use non-empty MCP tool names")
        return value


class MCPServersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "mcp_servers.v0"
    servers: list[MCPServerConfig] = Field(default_factory=list)


class MCPToolProvider:
    provider_id = "mcp"

    def __init__(
        self,
        *,
        config: MCPServersConfig | dict[str, Any] | None = None,
        clients: Mapping[str, MCPToolCatalogClient] | None = None,
    ) -> None:
        self.config = config if isinstance(config, MCPServersConfig) else MCPServersConfig.model_validate(config or {})
        self.clients = dict(clients or {})

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        result = ToolProviderResult()
        for server in self.config.servers:
            if not server.enabled:
                result.diagnostics.append(
                    diagnostic(self.provider_id, "info", "MCP server is disabled", server_id=server.server_id)
                )
                continue
            result.runtime_dependencies.append(
                RuntimeDependency(
                    dependency_id=f"mcp.{server.server_id}",
                    kind="mcp_server",
                    required=server.required,
                    details=server.model_dump(mode="json"),
                )
            )
            client = self.clients.get(server.server_id)
            if client is None:
                level = "error" if server.required else "warning"
                result.diagnostics.append(
                    diagnostic(
                        self.provider_id,
                        level,
                        "MCP client is not available for configured server",
                        server_id=server.server_id,
                    )
                )
                continue
            try:
                discovered = list(client.list_tools())
            except Exception as exc:
                level = "error" if server.required else "warning"
                result.diagnostics.append(
                    diagnostic(
                        self.provider_id,
                        level,
                        "failed to list MCP tools",
                        server_id=server.server_id,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            for discovered_tool in discovered:
                tool_name = _discovered_tool_name(discovered_tool)
                try:
                    tool = MCPDiscoveredTool.model_validate(discovered_tool)
                    tool_name = tool.name
                    prepared = prepare_mcp_tool(server, tool)
                    result.tool_specs.append(prepared.spec)
                    result.system_tool_ids.append(prepared.spec.id)
                    if prepared.repairs:
                        result.diagnostics.append(
                            diagnostic(
                                self.provider_id,
                                "warning",
                                "normalized non-standard MCP JSON Schema shorthand",
                                server_id=server.server_id,
                                tool_name=tool_name,
                                repairs=list(prepared.repairs),
                            )
                        )
                except Exception as exc:
                    result.diagnostics.append(
                        diagnostic(
                            self.provider_id,
                            "error",
                            "failed to convert MCP tool to ToolSpec",
                            server_id=server.server_id,
                            tool_name=tool_name,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
        return result


def _discovered_tool_name(tool: MCPDiscoveredTool | dict[str, Any] | Any) -> str:
    if isinstance(tool, MCPDiscoveredTool):
        return tool.name
    if isinstance(tool, dict):
        return str(tool.get("name") or "unknown")
    return str(getattr(tool, "name", "") or "unknown")


def prepare_mcp_tool(server: MCPServerConfig, tool: MCPDiscoveredTool) -> PreparedMCPTool:
    normalized_input = normalize_mcp_schema(
        tool.input_schema or {"type": "object", "additionalProperties": True}
    )
    normalized_output = normalize_mcp_schema(
        tool.output_schema or {"type": "object", "additionalProperties": True}
    )
    normalized_tool = tool.model_copy(
        update={
            "input_schema": normalized_input.schema,
            "output_schema": normalized_output.schema,
        }
    )
    spec = _tool_spec_from_mcp_tool(server, normalized_tool)
    _validate_mcp_tool_schemas(spec)
    repairs = tuple(
        [
            {"schema": "input", **repair.as_dict()}
            for repair in normalized_input.repairs
        ]
        + [
            {"schema": "output", **repair.as_dict()}
            for repair in normalized_output.repairs
        ]
    )
    return PreparedMCPTool(spec=spec, repairs=repairs)


def _validate_mcp_tool_schemas(spec: ToolSpec) -> None:
    compile_json_schema(schema=spec.input_schema, model_name=f"{spec.id}_mcp_input")
    compile_json_schema(schema=spec.output_schema, model_name=f"{spec.id}_mcp_output")


def _tool_spec_from_mcp_tool(server: MCPServerConfig, tool: MCPDiscoveredTool) -> ToolSpec:
    prefix = _snake(server.tool_id_prefix or server.server_id)
    tool_name = _snake(tool.name)
    tool_id = tool_name if tool_name.startswith(f"{prefix}_") else f"{prefix}_{tool_name}"
    return ToolSpec(
        id=tool_id,
        description=tool.description or f"MCP tool {tool.name} from server {server.server_id}.",
        description_context=server.tool_description_contexts.get(
            tool.name,
            ToolDescriptionContextConfig(),
        ),
        entrypoint=f"mcp:{server.server_id}/{tool.name}",
        input_schema=_apply_input_property_enums(
            tool.input_schema or {"type": "object", "additionalProperties": True},
            server.tool_input_property_enums.get(tool.name, {}),
            tool_name=tool.name,
        ),
        output_schema=tool.output_schema or {"type": "object", "additionalProperties": True},
        resources={},
        risk_level=tool.risk_level or server.risk_level_default,
        risk_evaluator=tool.risk_evaluator or ToolRiskEvaluatorConfig(llm_mode="on_uncertain"),
        concurrent=server.concurrent_default if tool.concurrent is None else tool.concurrent,
        permission_scope="extension",
        loop_policy=server.tool_loop_policies.get(tool.name, ToolLoopPolicyConfig()),
    )


def _apply_input_property_enums(
    schema: dict[str, Any],
    overrides: dict[str, list[str]],
    *,
    tool_name: str,
) -> dict[str, Any]:
    if not overrides:
        return schema
    updated = deepcopy(schema)
    properties = updated.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"cannot apply input enum overrides to tool without object properties: {tool_name}")
    for property_name, allowed in overrides.items():
        property_schema = properties.get(property_name)
        if not isinstance(property_schema, dict):
            raise ValueError(f"input enum override references unknown property: {tool_name}.{property_name}")
        property_schema["enum"] = list(allowed)
    return updated


def _snake(value: str) -> str:
    text = SNAKE_CHARS.sub("_", value.strip().lower()).strip("_")
    if not text:
        text = "tool"
    if text[0].isdigit():
        text = f"tool_{text}"
    return text
