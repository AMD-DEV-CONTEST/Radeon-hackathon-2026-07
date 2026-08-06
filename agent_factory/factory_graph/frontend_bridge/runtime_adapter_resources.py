from __future__ import annotations

from typing import Any

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import bounded_int
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import SYSTEM_CHAT_PACKAGE_ID
from agent_factory.factory_graph.frontend_bridge.workspace_resources import FrontendWorkspaceService


WORKSPACE_FILE_PREVIEW_MAX_CHARS = 1_000_000


class RuntimeResourceCommandMixin:
    def workspace_manage(self, command: FactoryFrontendCommand) -> None:
        action = str(command.payload.get("action") or "roots").strip()
        workspace_service = FrontendWorkspaceService(
            agent_package_runtime=self.agent_package_runtime,
            session_manager=self.session_manager,
        )
        if action == "roots":
            result = workspace_service.roots(command.payload, session_record=self.session_record)
            self._emit_resource_event(command, "workspace_roots_listed", result)
            return
        if action == "list":
            result = workspace_service.list_entries(
                command.payload,
                scope=str(command.payload.get("scope") or "workdir"),
                relative_path=str(command.payload.get("path") or ""),
                session_record=self.session_record,
            )
            self._emit_resource_event(command, "workspace_entries_listed", result)
            return
        if action == "read":
            result = workspace_service.read_file(
                command.payload,
                scope=str(command.payload.get("scope") or "workdir"),
                relative_path=str(command.payload.get("path") or ""),
                max_chars=bounded_int(
                    command.payload.get("max_chars"),
                    default=20000,
                    minimum=1000,
                    maximum=WORKSPACE_FILE_PREVIEW_MAX_CHARS,
                ),
                session_record=self.session_record,
            )
            self._emit_resource_event(command, "workspace_file_read", result)
            return
        self._emit_error(command, f"unsupported workspace action: {action}")

    def knowledge_manage(self, command: FactoryFrontendCommand) -> None:
        package_id = _package_id_from_payload(command.payload)
        action = str(command.payload.get("action") or "list_sources").strip()
        result = self.agent_package_runtime.knowledge_manage(package_id, action, command.payload)
        event_type = {
            "list_sources": "knowledge_sources_listed",
            "list_documents": "knowledge_documents_listed",
            "search": "knowledge_search_completed",
            "open": "knowledge_document_read",
            "read": "knowledge_document_read",
            "prepare_source": "knowledge_source_preview_available",
            "confirm_source": "knowledge_source_registered",
            "remove_source": "knowledge_source_removed",
            "reindex": "knowledge_source_reindex_requested",
        }.get(action)
        if event_type is None:
            self._emit_error(command, f"unsupported knowledge action: {action}")
            return
        self._emit_resource_event(
            command,
            event_type,
            {
                "package_id": package_id,
                **_optional_resource_mode(command.payload),
                **result,
            },
        )

    def extensions_manage(self, command: FactoryFrontendCommand) -> None:
        resource_mode = str(command.payload.get("resource_mode") or "").strip()
        package_id = _package_id_from_payload(command.payload)
        action = str(command.payload.get("action") or "list").strip()
        def emit_progress(server_id: str, line: str) -> None:
            self._emit_resource_event(
                command,
                "extension_config_test_output_delta",
                {
                    "package_id": package_id,
                    **_optional_resource_mode(command.payload),
                    "server_id": server_id,
                    "line": line,
                },
            )

        progress = emit_progress if action in {"install_mcp", "test_mcp"} else None
        if resource_mode in {"create_agent", "evolve_agent"}:
            result = self.agent_package_runtime.system_extensions_manage(
                resource_mode,
                action,
                command.payload,
                request_id=command.request_id,
                progress=progress,
            )
        else:
            result = self.agent_package_runtime.extensions_manage(
                package_id,
                action,
                command.payload,
                request_id=command.request_id,
                progress=progress,
            )
        event_type = "extension_configs_listed"
        if action in {
            "upsert_mcp",
            "install_mcp",
            "remove_mcp",
            "set_binding",
            "upsert_skill",
            "remove_skill",
            "update_tool_permissions",
            "set_tool_permission",
            "reset_tool_permission",
            "update_tool_configuration",
            "reset_tool_configuration",
            "skillhub_install",
        }:
            install = result.get("install") if isinstance(result.get("install"), dict) else {}
            event_type = (
                "extension_config_tested"
                if action == "install_mcp" and install.get("status") != "ok"
                else "extension_config_updated"
            )
        elif action == "test_mcp":
            event_type = "extension_config_tested"
        elif action in {"skillhub_status", "skillhub_search"}:
            event_type = "extension_skillhub_result"
        self._emit_resource_event(command, event_type, result)

    def _emit_resource_event(
        self,
        command: FactoryFrontendCommand,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.emit(
            event(
                event_type,
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload=payload,
            )
        )


def _package_id_from_payload(payload: dict[str, Any]) -> str:
    package_id = str(payload.get("package_id") or "").strip()
    return package_id or SYSTEM_CHAT_PACKAGE_ID


def _optional_resource_mode(payload: dict[str, Any]) -> dict[str, str]:
    resource_mode = str(payload.get("resource_mode") or "").strip()
    return {"resource_mode": resource_mode} if resource_mode else {}
