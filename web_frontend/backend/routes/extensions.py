from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import optional_package, optional_resource_mode, resource_command


def create_extensions_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/extensions")

    @router.get("")
    async def list_extensions(package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {"action": "list", **optional_package(package_id), **optional_resource_mode(resource_mode)},
            {"extension_configs_listed"},
        )
        return {"event": event}

    @router.put("/bindings")
    async def set_extension_binding(payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "set_binding",
                "kind": payload.get("kind"),
                "identifier": payload.get("identifier"),
                "enabled": payload.get("enabled", True),
                **optional_package(payload.get("package_id")),
                **optional_resource_mode(payload.get("resource_mode")),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.post("/mcp")
    async def save_mcp(payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {"action": "upsert_mcp", **payload, **optional_resource_mode(payload.get("resource_mode"))},
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.post("/mcp/install")
    async def install_mcp(payload: dict[str, Any]):
        request_id_value = str(payload.pop("request_id", "")).strip() or None
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {"action": "install_mcp", **payload, **optional_resource_mode(payload.get("resource_mode"))},
            {"extension_config_updated", "extension_config_tested"},
            timeout_seconds=None,
            request_id_value=request_id_value,
        )
        return {"event": event}

    @router.post("/mcp/test")
    async def test_mcp(payload: dict[str, Any]):
        request_id_value = str(payload.pop("request_id", "")).strip() or None
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {"action": "test_mcp", **payload, **optional_resource_mode(payload.get("resource_mode"))},
            {"extension_config_tested"},
            timeout_seconds=None,
            request_id_value=request_id_value,
        )
        return {"event": event}

    @router.get("/mcp/{server_id}")
    async def get_mcp_config(
        server_id: str,
        package_id: str | None = None,
        resource_mode: str | None = None,
    ):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "get_mcp_config",
                "server_id": server_id,
                **optional_package(package_id),
                **optional_resource_mode(resource_mode),
            },
            {"extension_configs_listed"},
        )
        return {"event": event}

    @router.delete("/mcp/{server_id}")
    async def remove_mcp(server_id: str, package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "remove_mcp",
                "server_id": server_id,
                **optional_package(package_id),
                **optional_resource_mode(resource_mode),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.post("/skills")
    async def save_skill(payload: dict[str, Any]):
        package_id = payload.get("package_id")
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "upsert_skill",
                "skill": payload.get("skill") if isinstance(payload.get("skill"), dict) else payload,
                "replace_skill_id": payload.get("replace_skill_id"),
                **optional_package(package_id),
                **optional_resource_mode(payload.get("resource_mode")),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.delete("/skills/{skill_id}")
    async def remove_skill(skill_id: str, package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "remove_skill",
                "skill_id": skill_id,
                **optional_package(package_id),
                **optional_resource_mode(resource_mode),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.get("/skills/skillhub/status")
    async def skillhub_status(package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "skillhub_status",
                **optional_package(package_id),
                **optional_resource_mode(resource_mode),
            },
            {"extension_skillhub_result"},
        )
        return {"event": event}

    @router.post("/skills/skillhub/search")
    async def skillhub_search(payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "skillhub_search",
                "query": payload.get("query"),
                **optional_package(payload.get("package_id")),
                **optional_resource_mode(payload.get("resource_mode")),
            },
            {"extension_skillhub_result"},
            timeout_seconds=90.0,
        )
        return {"event": event}

    @router.post("/skills/skillhub/install")
    async def skillhub_install(payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "skillhub_install",
                "skill": payload.get("skill"),
                **optional_package(payload.get("package_id")),
                **optional_resource_mode(payload.get("resource_mode")),
            },
            {"extension_config_updated"},
            timeout_seconds=240.0,
        )
        return {"event": event}

    @router.put("/tool-permissions")
    async def update_tool_permissions(payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "update_tool_permissions",
                "policy": payload.get("policy") if isinstance(payload.get("policy"), dict) else payload,
                **optional_package(payload.get("package_id")),
                **optional_resource_mode(payload.get("resource_mode")),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.patch("/tool-permissions/{tool_id}")
    async def set_tool_permission(tool_id: str, payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "set_tool_permission",
                "tool_id": tool_id,
                "override": payload.get("override") if isinstance(payload.get("override"), dict) else payload,
                **optional_package(payload.get("package_id")),
                **optional_resource_mode(payload.get("resource_mode")),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.delete("/tool-permissions/{tool_id}")
    async def reset_tool_permission(tool_id: str, package_id: str | None = None, resource_mode: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "reset_tool_permission",
                "tool_id": tool_id,
                **optional_package(package_id),
                **optional_resource_mode(resource_mode),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    return router
