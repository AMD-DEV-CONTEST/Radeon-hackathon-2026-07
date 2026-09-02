"""Minimal API-key status probe for desktop startup and reconnect flows."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies.auth import probe_api_key_status


router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthStatusResponse(BaseModel):
    protocol_version: Literal["1.0"]
    status: Literal["missing", "invalid", "valid"]
    valid: bool
    role: Literal["admin", "user"] | None = None
    deployment_mode: Literal[
        "local_desktop",
        "competition_local",
        "hosted_bridge",
        "full_server_deployment",
    ]
    deployment_enabled: bool
    deployment_stage: Literal["enabled", "planned"]
    data_authority: Literal["local", "server"]
    authenticated: bool
    effective_role: Literal["owner", "admin", "author", "reader"] | None = None
    capabilities: list[str]
    credential_status: Literal["missing", "invalid", "valid"]


@router.get("/status", response_model=AuthStatusResponse)
def get_auth_status(status: dict = Depends(probe_api_key_status)):
    """Report credential usability without echoing credential material."""
    return status
