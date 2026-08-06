from __future__ import annotations

import mimetypes
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.agent_group_system.store import AgentGroupStore
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import SYSTEM_CHAT_PACKAGE_ID
from agent_factory.factory_graph.frontend_bridge.workspace_resources import FrontendWorkspaceService
from agent_factory.factory_graph.session import FactorySessionManager
from agent_factory.native_directory_picker import (
    NativeDirectoryPicker,
    NativeDirectoryPickerUnavailableError,
)
from agent_factory.workspace_system import WorkspaceStore
from agent_factory.workspace_directories import WorkspaceDirectoryBrowser
from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import optional_package, resource_command


class WorkspaceMountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    name: str | None = None


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    mode: Literal["isolated", "project"] = "isolated"
    root_kind: Literal["managed", "linked"] = "managed"
    workdir_root: str | None = None
    owner_package_id: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    mode: Literal["isolated", "project"] | None = None
    archived: bool | None = None


class DirectorySelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_path: str | None = None


def create_workspace_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/workspace")

    @router.get("/projects")
    def list_workspaces(include_archived: bool = False):
        return {
            "workspaces": [
                record.model_dump(mode="json")
                for record in WorkspaceStore().list(include_archived=include_archived)
            ]
        }

    @router.post("/projects")
    def create_workspace(payload: WorkspaceCreateRequest):
        try:
            record = WorkspaceStore().create(
                title=payload.title,
                mode=payload.mode,
                root_kind=payload.root_kind,
                owner_package_id=payload.owner_package_id,
                workdir_root=Path(payload.workdir_root) if payload.workdir_root else None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"workspace": record.model_dump(mode="json")}

    @router.get("/directory-roots")
    def workspace_directory_roots():
        try:
            return {"roots": WorkspaceDirectoryBrowser().root_views()}
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/directories")
    def workspace_directories(path: str):
        try:
            return WorkspaceDirectoryBrowser().list_directories(path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/select-directory")
    def select_workspace_directory(payload: DirectorySelectionRequest, request: Request):
        client_host = request.client.host if request.client else ""
        try:
            is_loopback = ip_address(client_host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise HTTPException(
                status_code=403,
                detail="native directory selection is available only from the local host",
            )
        try:
            selected = NativeDirectoryPicker().select(payload.initial_path)
        except NativeDirectoryPickerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(selected) if selected else None}

    @router.patch("/projects/{workspace_id}")
    def update_workspace(workspace_id: str, payload: WorkspaceUpdateRequest):
        try:
            record = WorkspaceStore().update(
                workspace_id,
                title=payload.title,
                mode=payload.mode,
                archived=payload.archived,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"workspace": record.model_dump(mode="json")}

    @router.delete("/projects/{workspace_id}")
    def delete_workspace(workspace_id: str, delete_files: bool = True):
        references = _workspace_session_references(workspace_id)
        if references:
            raise HTTPException(
                status_code=409,
                detail={"message": "workspace still has sessions", "sessions": references},
            )
        try:
            record = WorkspaceStore().delete(workspace_id, delete_files=delete_files)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "deleted": True,
            "workspace_id": record.workspace_id,
            "files_deleted": delete_files,
        }

    @router.get("/mounts")
    def list_workspace_mounts(
        package_id: str | None = None,
        package_session_id: str | None = None,
    ):
        resolved_package_id, resolved_session_id = _workspace_mount_context(
            package_id,
            package_session_id,
        )
        try:
            mounts = AgentPackageRuntimeManager().list_workspace_mounts(
                resolved_package_id,
                resolved_session_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "package_id": resolved_package_id,
            "package_session_id": resolved_session_id,
            "mounts": mounts,
        }

    @router.post("/mounts")
    def mount_workspace_directory(
        payload: WorkspaceMountRequest,
        package_id: str | None = None,
        package_session_id: str | None = None,
    ):
        resolved_package_id, resolved_session_id = _workspace_mount_context(
            package_id,
            package_session_id,
        )
        try:
            return AgentPackageRuntimeManager().mount_workspace_directory(
                resolved_package_id,
                resolved_session_id,
                source_path=payload.source_path,
                name=payload.name,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/mounts/{mount_id}")
    def unmount_workspace_directory(
        mount_id: str,
        package_id: str | None = None,
        package_session_id: str | None = None,
    ):
        resolved_package_id, resolved_session_id = _workspace_mount_context(
            package_id,
            package_session_id,
        )
        try:
            return AgentPackageRuntimeManager().unmount_workspace_directory(
                resolved_package_id,
                resolved_session_id,
                mount_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/roots")
    async def workspace_roots(
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
        create_agent_session_id: str | None = None,
        group_id: str | None = None,
    ):
        event = await resource_command(
            runtime_bridge,
            "workspace_manage",
            {
                "action": "roots",
                **workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    workspace_id=workspace_id,
                    create_agent_session_id=create_agent_session_id,
                    group_id=group_id,
                ),
            },
            {"workspace_roots_listed"},
        )
        return {"event": event}

    @router.get("/entries")
    async def workspace_entries(
        scope: str = "workdir",
        path: str = "",
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
        create_agent_session_id: str | None = None,
        group_id: str | None = None,
    ):
        event = await resource_command(
            runtime_bridge,
            "workspace_manage",
            {
                "action": "list",
                "scope": scope,
                "path": path,
                **workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    workspace_id=workspace_id,
                    create_agent_session_id=create_agent_session_id,
                    group_id=group_id,
                ),
            },
            {"workspace_entries_listed"},
        )
        return {"event": event}

    @router.get("/file")
    async def workspace_file(
        scope: str = "workdir",
        path: str = "",
        max_chars: int = Query(default=120000, ge=1000, le=1_000_000),
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
        create_agent_session_id: str | None = None,
        group_id: str | None = None,
    ):
        event = await resource_command(
            runtime_bridge,
            "workspace_manage",
            {
                "action": "read",
                "scope": scope,
                "path": path,
                "max_chars": max_chars,
                **workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    workspace_id=workspace_id,
                    create_agent_session_id=create_agent_session_id,
                    group_id=group_id,
                ),
            },
            {"workspace_file_read"},
        )
        return {"event": event}

    @router.get("/raw")
    def workspace_raw_file(
        scope: str = "workdir",
        path: str = "",
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
        create_agent_session_id: str | None = None,
        group_id: str | None = None,
    ):
        service = FrontendWorkspaceService(
            agent_package_runtime=AgentPackageRuntimeManager(),
            session_manager=FactorySessionManager.from_env(),
        )
        try:
            target = service.resolve_file(
                workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    workspace_id=workspace_id,
                    create_agent_session_id=create_agent_session_id,
                    group_id=group_id,
                ),
                scope=scope,
                relative_path=path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        filename = target.name
        quoted_filename = quote(filename)
        return FileResponse(
            target,
            media_type=media_type,
            filename=filename,
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{quoted_filename}"},
        )

    @router.get("/native-path")
    def workspace_native_path(
        scope: str = "workdir",
        path: str = "",
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
        create_agent_session_id: str | None = None,
        group_id: str | None = None,
    ):
        service = FrontendWorkspaceService(
            agent_package_runtime=AgentPackageRuntimeManager(),
            session_manager=FactorySessionManager.from_env(),
        )
        try:
            target = service.resolve_entry(
                workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    workspace_id=workspace_id,
                    create_agent_session_id=create_agent_session_id,
                    group_id=group_id,
                ),
                scope=scope,
                relative_path=path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "native_path": str(target),
            "kind": "directory" if target.is_dir() else "file",
        }

    @router.delete("/file")
    def delete_workspace_file(
        scope: str = "workdir",
        path: str = "",
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
        create_agent_session_id: str | None = None,
        group_id: str | None = None,
    ):
        service = FrontendWorkspaceService(
            agent_package_runtime=AgentPackageRuntimeManager(),
            session_manager=FactorySessionManager.from_env(),
        )
        try:
            return service.delete_file(
                workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    workspace_id=workspace_id,
                    create_agent_session_id=create_agent_session_id,
                    group_id=group_id,
                ),
                scope=scope,
                relative_path=path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router


def workspace_context_payload(
    *,
    package_id: str | None,
    resource_mode: str | None,
    factory_session_id: str | None,
    package_session_id: str | None,
    workspace_id: str | None,
    create_agent_session_id: str | None,
    group_id: str | None,
) -> dict[str, str]:
    return {
        **optional_package(package_id),
        **({"resource_mode": resource_mode} if resource_mode else {}),
        **({"factory_session_id": factory_session_id} if factory_session_id else {}),
        **({"package_session_id": package_session_id} if package_session_id else {}),
        **({"workspace_id": workspace_id} if workspace_id else {}),
        **({"create_agent_session_id": create_agent_session_id} if create_agent_session_id else {}),
        **({"group_id": group_id} if group_id else {}),
    }


def _workspace_mount_context(
    package_id: str | None,
    package_session_id: str | None,
) -> tuple[str, str]:
    resolved_package_id = str(package_id or "").strip() or SYSTEM_CHAT_PACKAGE_ID
    resolved_session_id = str(package_session_id or "").strip()
    if not resolved_session_id:
        raise HTTPException(
            status_code=400,
            detail="package_session_id is required to manage workspace mounts",
        )
    return resolved_package_id, resolved_session_id


def _workspace_session_references(workspace_id: str) -> list[dict[str, str]]:
    target = str(workspace_id or "").strip()
    manager = AgentPackageRuntimeManager()
    references: list[dict[str, str]] = []
    for package in manager.list_packages():
        package_id = str(package.get("package_id") or "").strip()
        if not package_id:
            continue
        for session in manager.list_sessions(package_id):
            if str(session.get("workspace_id") or "").strip() != target:
                continue
            references.append(
                {
                    "package_id": package_id,
                    "session_id": str(session.get("session_id") or ""),
                }
            )
    for group in AgentGroupStore().list_groups():
        if str(group.get("workspace_id") or "").strip() != target:
            continue
        references.append(
            {
                "package_id": "agent_group",
                "session_id": str(group.get("group_id") or ""),
            }
        )
    return references
