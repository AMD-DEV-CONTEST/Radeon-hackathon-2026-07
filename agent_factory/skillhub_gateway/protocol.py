from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SkillHubGatewayError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    where: str
    message: str
    error_type: str = "SkillHubGatewayError"


class SkillHubGatewayHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    version: str = "skillhub_gateway.v0"
    extension_root: str


class SkillHubGatewayRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["status", "search", "install"]
    query: str | None = None
    skill: str | None = None


class SkillHubGatewayRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "skillhub_gateway.v0"
    result: dict[str, Any] = Field(default_factory=dict)
