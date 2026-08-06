from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MCPGatewayError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    where: str
    message: str
    error_type: str = "MCPGatewayError"


class MCPGatewayToolDescriptor(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class MCPGatewayHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    version: str = "mcp_gateway.v0"
    server_count: int


class MCPGatewayServersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "mcp_gateway.v0"
    servers: list[str] = Field(default_factory=list)


class MCPGatewayListToolsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "mcp_gateway.v0"
    server_id: str
    tools: list[MCPGatewayToolDescriptor] = Field(default_factory=list)


class MCPGatewayCallToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPGatewayCallToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "mcp_gateway.v0"
    server_id: str
    tool_name: str
    result: dict[str, Any] = Field(default_factory=dict)

