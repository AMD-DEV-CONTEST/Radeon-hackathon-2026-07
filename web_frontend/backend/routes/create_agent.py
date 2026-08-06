from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from agent_factory.create_agent.publish_tool import confirm_and_publish
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.environment_system import EnvironmentResolutionError
from agent_factory.resource_system import ResourceStore
from agent_factory.runtime_contracts import AgentPackageLoader, ResourcesContract


def create_create_agent_router() -> APIRouter:
    router = APIRouter(prefix="/api/create-agent")

    @router.post("/workspaces/{workspace_id}/publish")
    async def publish_create_agent_workspace(workspace_id: str, payload: dict[str, Any] | None = None):
        confirmation = _confirmation_text(payload)
        try:
            result = await asyncio.to_thread(
                confirm_and_publish,
                workspace=CreateAgentWorkspace.for_session(workspace_id),
                confirmation=confirmation,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except EnvironmentResolutionError as exc:
            raise HTTPException(
                status_code=409,
                detail={"status": exc.status, "message": str(exc)},
            ) from exc
        return {"published": result}

    @router.put("/workspaces/{workspace_id}/resources/{resource_id}")
    async def put_create_agent_resource(workspace_id: str, resource_id: str, payload: dict[str, Any]):
        if "value" not in payload:
            raise HTTPException(status_code=400, detail="resource value is required")
        workspace = CreateAgentWorkspace.for_session(workspace_id)
        try:
            package = AgentPackageLoader().load_path(workspace.package_manifest_path())
            contract = ResourcesContract.model_validate(package.contracts.get("resources") or {})
            descriptors = {item.resource_id: item for item in contract.config.resource_descriptors}
            descriptor = descriptors.get(resource_id)
            if descriptor is None:
                raise ValueError(f"resource is not declared by the manufacturing package: {resource_id}")
            result = ResourceStore().put(workspace.root.name, descriptor, payload["value"])
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return result

    return router


def _confirmation_text(payload: dict[str, Any] | None) -> str:
    if isinstance(payload, dict):
        text = str(payload.get("confirmation") or "").strip()
        if text:
            return text
    return "用户在 Web 界面点击发布"
