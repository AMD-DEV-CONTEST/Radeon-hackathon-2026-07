from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import send_and_wait

logger = logging.getLogger(__name__)


def create_agent_package_router(runtime_bridge: RuntimeBridge, logger: logging.Logger) -> APIRouter:
    router = APIRouter(prefix="/api/agent-packages")

    @router.get("")
    async def list_agent_packages():
        event = await send_and_wait(runtime_bridge, "list_agent_packages", {}, {"agent_packages_listed"})
        return {"event": event}

    @router.post("/select")
    async def select_agent_package(payload: dict[str, Any]):
        event = await send_and_wait(runtime_bridge, "select_agent_package", payload, {"agent_package_selected"})
        return {"event": event}

    @router.get("/instances")
    async def list_agent_package_instances():
        event = await send_and_wait(
            runtime_bridge,
            "list_agent_package_instances",
            {},
            {"agent_package_instances_listed"},
        )
        return {"event": event}

    @router.get("/recent-sessions")
    def list_recent_agent_package_sessions(limit: int = Query(default=5, ge=1, le=20)):
        runtime = AgentPackageRuntimeManager()
        return {"sessions": runtime.list_recent_sessions(limit=limit)}

    @router.post("/{package_id}/initialize")
    async def initialize_agent_package(package_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "initialize_agent_package",
            {"package_id": package_id},
            {"agent_package_instance_updated"},
            event_filter=lambda item: _is_initialize_status_event(item, package_id=package_id),
        )
        return {"event": event}

    @router.post("/{package_id}/shutdown")
    async def shutdown_agent_package_instance(package_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "shutdown_agent_package_instance",
            {"package_id": package_id},
            {"agent_package_instance_updated"},
        )
        return {"event": event}

    @router.delete("/{package_id}")
    async def delete_agent_package(package_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "delete_agent_package",
            {"package_id": package_id},
            {"agent_package_deleted"},
        )
        return {"event": event}

    @router.get("/{package_id}/export")
    def export_agent_package(package_id: str):
        try:
            archive_path = AgentPackageRuntimeManager().export_package_archive(package_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filename = f"{package_id}.zip"
        quoted_filename = quote(filename)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=filename,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"},
            background=BackgroundTask(unlink_file, archive_path),
        )

    @router.get("/{package_id}/tool-settings")
    def get_agent_package_tool_settings(package_id: str):
        try:
            summary = AgentPackageRuntimeManager().extension_config_summary(package_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tool_settings": summary.get("tool_permissions", {})}

    @router.patch("/{package_id}/tool-settings/policy")
    def update_agent_package_tool_policy(package_id: str, payload: dict[str, Any]):
        try:
            runtime = AgentPackageRuntimeManager()
            current = runtime.extension_config_summary(package_id)
            current_policy = current.get("tool_permissions", {}).get("policy", {})
            requested_policy = payload.get("policy", payload)
            if not isinstance(requested_policy, dict):
                raise ValueError("tool policy must be an object")
            if requested_policy.get("mode") == "allow_all":
                current_overrides = current_policy.get("tool_overrides", {})
                current_policy = {
                    **current_policy,
                    "tool_overrides": {
                        tool_id: {**override, "approval": "inherit"}
                        for tool_id, override in current_overrides.items()
                        if isinstance(override, dict) and override.get("risk_level") is not None
                    },
                }
            summary = runtime.extensions_manage(
                package_id,
                "update_tool_permissions",
                {"policy": {**current_policy, **requested_policy}},
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tool_settings": summary.get("tool_permissions", {})}

    @router.patch("/{package_id}/tool-settings/{tool_id}")
    def update_agent_package_tool_settings(package_id: str, tool_id: str, payload: dict[str, Any]):
        try:
            summary = AgentPackageRuntimeManager().extensions_manage(
                package_id,
                "update_tool_configuration",
                {**payload, "tool_id": tool_id},
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tool_settings": summary.get("tool_permissions", {})}

    @router.delete("/{package_id}/tool-settings/{tool_id}")
    def reset_agent_package_tool_settings(package_id: str, tool_id: str):
        try:
            summary = AgentPackageRuntimeManager().extensions_manage(
                package_id,
                "reset_tool_configuration",
                {"tool_id": tool_id},
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tool_settings": summary.get("tool_permissions", {})}

    @router.patch("/{package_id}/context-config")
    def update_agent_package_context_config(package_id: str, payload: dict[str, Any]):
        config = payload.get("config")
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="context config is required")
        try:
            summary = AgentPackageRuntimeManager().update_context_config(
                package_id,
                config=config,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"package": summary}

    @router.patch("/{package_id}/scheduler-config")
    def update_agent_package_scheduler_config(package_id: str, payload: dict[str, Any]):
        config = payload.get("config")
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="scheduler config is required")
        try:
            summary = AgentPackageRuntimeManager().update_scheduler_config(
                package_id,
                config=config,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"package": summary}

    @router.patch("/{package_id}/model-overrides")
    def update_agent_package_model_overrides(package_id: str, payload: dict[str, Any]):
        bindings = payload.get("bindings")
        tool_bindings = payload.get("tool_bindings")
        if not isinstance(bindings, dict) or not isinstance(tool_bindings, dict):
            raise HTTPException(status_code=400, detail="model and model tool overrides are required")
        try:
            summary = AgentPackageRuntimeManager().update_model_overrides(
                package_id,
                bindings=bindings,
                tool_bindings=tool_bindings,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"package": summary}

    @router.get("/{package_id}/resources")
    def get_agent_package_resources(package_id: str):
        try:
            return AgentPackageRuntimeManager().resource_status(package_id, include_values=True)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/{package_id}/resources/{resource_id}")
    def put_agent_package_resource(package_id: str, resource_id: str, payload: dict[str, Any]):
        if "value" not in payload:
            raise HTTPException(status_code=400, detail="resource value is required")
        try:
            return AgentPackageRuntimeManager().put_resource(package_id, resource_id, payload["value"])
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.delete("/{package_id}/resources/{resource_id}")
    def delete_agent_package_resource(package_id: str, resource_id: str):
        try:
            return AgentPackageRuntimeManager().delete_resource(package_id, resource_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{package_id}/sessions")
    async def list_agent_package_sessions(package_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "list_agent_package_sessions",
            {"package_id": package_id},
            {"agent_package_sessions_listed"},
        )
        return {"event": event}

    @router.get("/{package_id}/sessions/{session_id}")
    async def load_agent_package_session(package_id: str, session_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "load_agent_package_session",
            {"package_id": package_id, "session_id": session_id},
            {"agent_package_session_loaded"},
        )
        return {"event": event}

    @router.delete("/{package_id}/sessions/{session_id}")
    async def delete_agent_package_session(package_id: str, session_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "delete_agent_package_session",
            {"package_id": package_id, "session_id": session_id},
            {"agent_package_session_deleted"},
        )
        return {"event": event}

    return router


def _is_initialize_status_event(item: dict[str, Any], *, package_id: str) -> bool:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return str(payload.get("package_id") or "").strip() == package_id


def unlink_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove temporary file: %s", path)
