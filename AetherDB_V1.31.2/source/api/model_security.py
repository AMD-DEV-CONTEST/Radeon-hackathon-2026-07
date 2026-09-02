"""Administrative model data-boundary and controlled-tool policy APIs."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies.auth import require_capability
from app.deployment import Capability, EffectivePrincipal
from services.model_data_boundary import (
    ModelDataBoundaryError,
    get_model_data_policy,
    set_model_data_policy,
)
from services.model_tools import (
    ModelToolError,
    list_model_tool_policies,
    list_registered_tools,
    set_model_tool_policy,
)


router = APIRouter(prefix="/api/model-security", tags=["model_security"])
require_security_admin = require_capability(Capability.MANAGE_SECURITY)


class ModelDataPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission_tier: Literal[
        "A_PURE_CREATION",
        "B_CONTEXT_ENHANCED",
        "C_RESTRICTED_TOOLS",
    ]
    allow_original_text: bool = True
    allow_approved_context: bool = False
    allow_selected_media: bool = False
    max_payload_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)


class ModelToolPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def _security_http_error(exc):
    return HTTPException(
        exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("/data-policies/{model_profile_id}")
def get_data_policy(
    model_profile_id: str,
    _: EffectivePrincipal = Depends(require_security_admin),
):
    try:
        policy = get_model_data_policy(model_profile_id)
    except ModelDataBoundaryError as exc:
        raise _security_http_error(exc) from exc
    return {"protocol_version": "1.0", "policy": policy}


@router.put("/data-policies/{model_profile_id}")
def update_data_policy(
    model_profile_id: str,
    payload: ModelDataPolicyUpdate,
    principal: EffectivePrincipal = Depends(require_security_admin),
):
    try:
        policy = set_model_data_policy(
            model_profile_id,
            **payload.model_dump(),
            updated_by=f"role:{principal.credential_role}",
        )
    except ModelDataBoundaryError as exc:
        raise _security_http_error(exc) from exc
    return {"protocol_version": "1.0", "policy": policy}


@router.get("/tools")
def get_tools(_: EffectivePrincipal = Depends(require_security_admin)):
    return {"protocol_version": "1.0", "tools": list_registered_tools()}


@router.get("/models/{model_profile_id}/tools")
def get_model_tools(
    model_profile_id: str,
    _: EffectivePrincipal = Depends(require_security_admin),
):
    try:
        policies = list_model_tool_policies(model_profile_id)
    except ModelToolError as exc:
        raise _security_http_error(exc) from exc
    return {
        "protocol_version": "1.0",
        "model_profile_id": model_profile_id,
        "tools": policies,
    }


@router.put("/models/{model_profile_id}/tools/{tool_name}")
def update_model_tool(
    model_profile_id: str,
    tool_name: str,
    payload: ModelToolPolicyUpdate,
    principal: EffectivePrincipal = Depends(require_security_admin),
):
    try:
        policy = set_model_tool_policy(
            model_profile_id,
            tool_name,
            enabled=payload.enabled,
            updated_by=f"role:{principal.credential_role}",
        )
    except ModelToolError as exc:
        raise _security_http_error(exc) from exc
    return {"protocol_version": "1.0", "policy": policy}
