from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
import threading
from typing import Any, Iterator
from uuid import uuid4

from agent_factory.knowledge_system import KnowledgeIngestionWorker, KnowledgeRuntime, build_knowledge_runtime
from agent_factory.knowledge_system.schema import KnowledgeRuntimeConfig
from agent_factory.agent_registry import refresh_agent_registry_index
from agent_factory.runtime_contracts import ContextContract, LoadedAgentPackage
from agent_factory.model_pool.resolver import (
    resolve_available_chat_model,
    resolve_chat_model_binding,
)
from agent_factory.model_pool.schema import ModelProfileBinding
from agent_factory.context_system.token_counter import (
    ModelContextLimits,
    context_limits_with_overrides,
    model_context_limits,
)
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.workspace_mounts import (
    WorkspaceMountRecord,
    WorkspaceMountService,
    workspace_mount_payload,
)
from agent_factory.workspace_system import WorkspaceRecord, WorkspaceStore
from agent_factory.runtime_kernel.persistence import delete_sqlite_checkpoint_thread
from agent_factory.mcp_gateway import HostMCPGatewayManager
from agent_factory.skillhub_gateway import HostSkillHubGatewayManager
from agent_factory.package_runtime import host_runtime_package_view
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy
from agent_factory.paths import project_root
from agent_factory.resource_system import ResourceStore, migrate_package_resources
from agent_factory.environment_system import EnvironmentResolver
from agent_factory.runtime_contracts import ResourcesContract
from agent_factory.runtime_attachments import (
    AttachmentImportResult,
    import_runtime_attachments,
    time_named_attachment_scope,
    workspace_attachment_root,
    workspace_attachment_runtime_root,
)
from agent_factory.tooling.extension_registry import default_extension_registry_root
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.agent_package_repository import (
    AgentPackageRepository,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_configuration import (
    AgentPackageConfigurationEditor,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_extensions import (
    AgentPackageExtensionService,
    extensions_summary as _extensions_summary,
    load_extension_bundle as _load_extension_bundle,
    package_extension_detail as _package_extension_detail,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_paths import (
    extension_root_for_package as _extension_root_for_package,
    host_runtime_root as _host_runtime_root,
    package_runtime_workspace as _package_runtime_workspace,
    host_package_workdir as _host_package_workdir,
    host_session_workdir as _host_session_workdir,
    is_host_system_package as _is_host_system_package,
    is_system_package as _is_system_package,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_utils import (
    humanize_identifier as _humanize_identifier,
    path_updated_at as _path_updated_at,
    read_json_object as _read_json_object,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_workspace import (
    AgentPackageWorkspaceService,
    workspace_roots,
)
from agent_factory.factory_graph.frontend_bridge.runtime_events import node_event, run_failed_event
from agent_factory.factory_graph.frontend_bridge.system_package_runtime_handle import SystemPackageRuntimeHandle
from agent_factory.native_runtime import AgentRuntimeLaunchError, NativeAgentRuntimeHandle, NativeAgentRuntimeLauncher


DEFAULT_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS = 1800
DEFAULT_AGENT_RUNTIME_INITIALIZE_TIMEOUT_SECONDS = 120
DEFAULT_AGENT_RUNTIME_BRIDGE_STARTUP_TIMEOUT_SECONDS = 30
Emit = Callable[[FactoryFrontendEvent], None]
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ResolvedWorkspace:
    record: WorkspaceRecord
    workdir: Path


@dataclass(frozen=True, slots=True)
class AgentPackageRunResult:
    package: LoadedAgentPackage
    final_state: Any
    session: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentPackageStreamRun:
    package: LoadedAgentPackage
    session: dict[str, Any]
    request_id: str
    events: Iterator[tuple[str, Any]]


@dataclass(slots=True)
class KnowledgeRuntimeHandle:
    runtime: KnowledgeRuntime
    worker: KnowledgeIngestionWorker
    package_fingerprint: str

    def close(self) -> None:
        self.worker.shutdown()


class AgentPackageRuntimeManager:
    def __init__(
        self,
        *,
        package_root: str | Path | None = None,
        system_package_root: str | Path | None = None,
        repository: AgentPackageRepository | None = None,
        launcher: NativeAgentRuntimeLauncher | None = None,
        emit: Emit | None = None,
    ) -> None:
        configured_root = package_root or os.getenv("AGENTFACTORY_PACKAGE_ROOT")
        configured_system_root = system_package_root or os.getenv("AGENTFACTORY_SYSTEM_PACKAGE_ROOT")
        self.repository = repository or AgentPackageRepository.from_paths(
            package_root=configured_root,
            system_package_root=configured_system_root,
        )
        self.launcher = launcher or NativeAgentRuntimeLauncher()
        self.workspace = AgentPackageWorkspaceService()
        self.extensions = AgentPackageExtensionService()
        self.idle_timeout_seconds = _env_int(
            "AGENTFACTORY_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS",
            DEFAULT_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS,
        )
        self.request_policy = RuntimeRequestPolicy.from_env()
        self.initialize_timeout_seconds = _env_int(
            "AGENTFACTORY_AGENT_RUNTIME_INITIALIZE_TIMEOUT_SECONDS",
            DEFAULT_AGENT_RUNTIME_INITIALIZE_TIMEOUT_SECONDS,
        )
        self.bridge_startup_timeout_seconds = _env_int(
            "AGENTFACTORY_AGENT_RUNTIME_BRIDGE_STARTUP_TIMEOUT_SECONDS",
            DEFAULT_AGENT_RUNTIME_BRIDGE_STARTUP_TIMEOUT_SECONDS,
        )
        self._containers: dict[str, NativeAgentRuntimeHandle] = {}
        self._system_handles: dict[str, SystemPackageRuntimeHandle] = {}
        self._knowledge_handles: dict[str, KnowledgeRuntimeHandle] = {}
        self._runtime_handle_lock = threading.RLock()
        self._package_initialization_locks: dict[str, threading.Lock] = {}
        self._instance_status_overrides: dict[str, dict[str, Any]] = {}
        self._mcp_gateways = HostMCPGatewayManager()
        self._container_mcp_gateway_keys: dict[str, str] = {}
        self._skillhub_gateways = HostSkillHubGatewayManager()
        self._emit = emit
        self.resource_store = ResourceStore()
        self._resource_migration = self._migrate_package_resources()
        self._environment_preparation_errors: dict[str, str] = {}

    def set_emit(self, emit: Emit | None) -> None:
        self._emit = emit
        for handle in self._containers.values():
            handle.set_emit(emit)
        for handle in self._system_handles.values():
            handle.set_emit(emit)

    def emit_frontend_event(self, item: FactoryFrontendEvent) -> None:
        if self._emit is None:
            return
        self._emit(item)

    def list_packages(self) -> list[dict[str, Any]]:
        packages = [
            self._package_summary(manifest_path)
            for manifest_path in self.repository.manifest_paths()
        ]
        return sorted(packages, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def resource_status(self, package_id: str, *, include_values: bool = False) -> dict[str, Any]:
        package = self.load_package(package_id)
        contract = ResourcesContract.model_validate(package.contracts.get("resources") or {})
        return {
            "package_id": package_id,
            "key_available": self.resource_store.key_available,
            "resources": self.resource_store.status(
                package_id,
                contract.config.resource_descriptors,
                include_values=include_values,
            ),
            "migration": self._resource_migration.get(package_id, {"status": "complete", "migrated": False}),
        }

    def put_resource(self, package_id: str, resource_id: str, value: Any) -> dict[str, Any]:
        package = self.load_package(package_id)
        contract = ResourcesContract.model_validate(package.contracts.get("resources") or {})
        descriptors = {item.resource_id: item for item in contract.config.resource_descriptors}
        descriptor = descriptors.get(resource_id)
        if descriptor is None:
            raise ValueError(f"resource is not declared by package: {resource_id}")
        return self.resource_store.put(package_id, descriptor, value)

    def delete_resource(self, package_id: str, resource_id: str) -> dict[str, Any]:
        return {"package_id": package_id, "resource_id": resource_id, "deleted": self.resource_store.delete(package_id, resource_id)}

    def _migrate_package_resources(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for manifest_path in self.repository.manifest_paths():
            try:
                results[manifest_path.parent.name] = migrate_package_resources(manifest_path.parent, store=self.resource_store)
            except Exception as exc:
                results[manifest_path.parent.name] = {"status": "pending", "reason": f"{type(exc).__name__}: {exc}"}
        return results

    def load_package(self, package_id: str) -> LoadedAgentPackage:
        return self.repository.load(package_id)

    def runtime_root_for_package(self, package_id: str) -> Path:
        return _host_runtime_root(package_id)

    def workdir_for_package(self, package_id: str) -> Path:
        return _host_package_workdir(package_id)

    def workdir_for_session(self, package_id: str, session_id: str) -> Path:
        return self._workspace_for_session(package_id, session_id).workdir

    def _workspace_for_session(self, package_id: str, session_id: str):
        package = self.load_package(package_id)
        session = self._session_manager_for_package(package_id, package).load(session_id)
        store = WorkspaceStore()
        record = store.load_optional(session.workspace_id)
        if record is None:
            legacy_workdir = _host_session_workdir(package_id, session_id)
            record = store.create(
                workspace_id=session.workspace_id,
                title=session.display_title or session.first_user_input or "新工作区",
                mode="isolated",
                owner_package_id=package_id,
                workdir_root=legacy_workdir if legacy_workdir.exists() else None,
            )
        if session.legacy_workspace_mounts:
            known_mount_ids = {mount.mount_id for mount in record.mounts}
            record.mounts.extend(
                mount
                for mount in session.legacy_workspace_mounts
                if mount.mount_id not in known_mount_ids
            )
            store.save(record)
            self._session_manager_for_package(package_id, package).save(session)
        return _ResolvedWorkspace(record=record, workdir=store.workdir(record.workspace_id))

    def list_instance_statuses(self) -> list[dict[str, Any]]:
        package_ids = {item.get("package_id") for item in self.list_packages()}
        package_ids.update(handle.package_id for handle in self._containers.values())
        package_ids.update(handle.package_id for handle in self._system_handles.values())
        return [
            self.package_instance_status(str(package_id))
            for package_id in sorted(item for item in package_ids if item)
        ]

    def package_instance_status(self, package_id: str) -> dict[str, Any]:
        package = self.load_package(package_id)
        backend = "host" if _is_host_system_package(package) else "local"
        handles = self._runtime_handles_for_package(package_id, backend=backend)
        running = any(bool(getattr(handle, "is_running", False)) for handle in handles)
        active_request_count = sum(int(getattr(handle, "active_request_count", 0)) for handle in handles)
        active_command_types: set[str] = set()
        for handle in handles:
            active_command_types.update(str(item) for item in getattr(handle, "active_command_types", ()))
        base = {
            "package_id": package_id,
            "agent_id": package.assembly_spec.agent.id,
            "agent_name": package.assembly_spec.agent.name,
            "backend": backend,
            "status": "ready" if running else "stopped",
            "ready": running,
            "active_request_count": active_request_count,
            "runtime_root": str(_host_runtime_root(package_id)),
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }
        if running and "initialize_runtime" in active_command_types:
            base.update({"status": "initializing", "ready": False})
        override = self._instance_status_overrides.get(package_id)
        if override:
            base.update(override)
            if not running and base.get("status") != "failed":
                base.update({"status": "stopped", "ready": False})
        return base

    def initialize_package(
        self,
        package_id: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        initialization_lock = self._package_initialization_lock(package_id)
        acquired = initialization_lock.acquire(blocking=False)
        if not acquired:
            self._publish_instance_status(
                package_id=package_id,
                package=package,
                request_id=request_id,
                status="initializing",
                ready=False,
                stage="waiting_for_package_initialization",
            )
            initialization_lock.acquire()
        try:
            if self._package_runtime_is_initialized(package_id, package):
                return self.package_instance_status(package_id)
            return self._initialize_package_locked(
                package_id,
                package=package,
                request_id=request_id,
            )
        finally:
            initialization_lock.release()

    def _package_initialization_lock(self, package_id: str) -> threading.Lock:
        with self._runtime_handle_lock:
            lock = self._package_initialization_locks.get(package_id)
            if lock is None:
                lock = threading.Lock()
                self._package_initialization_locks[package_id] = lock
            return lock

    def _initialize_package_locked(
        self,
        package_id: str,
        *,
        package: LoadedAgentPackage,
        request_id: str | None,
    ) -> dict[str, Any]:
        self._publish_instance_status(
            package_id=package_id,
            package=package,
            request_id=request_id,
            status="initializing",
            ready=False,
            stage="preparing_environment",
        )
        command = {
            "type": "initialize_runtime",
            "request_id": request_id or uuid4().hex,
            "payload": {
                "runtime_request": RuntimeRequestPolicy(
                    timeout_seconds=self.initialize_timeout_seconds,
                    heartbeat_seconds=self.request_policy.heartbeat_seconds,
                ).as_payload(),
            },
        }
        latest_status: dict[str, Any] | None = None
        environment_prepared = False
        try:
            EnvironmentResolver().ensure(
                package.package_root,
                on_progress=lambda stage, detail: self._publish_instance_status(
                    package_id=package_id,
                    package=package,
                    request_id=request_id,
                    status="initializing",
                    ready=False,
                    stage=stage,
                    detail=detail,
                ),
            )
            environment_prepared = True
            self._environment_preparation_errors.pop(package_id, None)
            self._publish_instance_status(
                package_id=package_id,
                package=package,
                request_id=request_id,
                status="initializing",
                ready=False,
                stage="starting_runtime",
            )
            for stream_mode, chunk in self._runtime_events(package_id, package=package, command=command):
                if stream_mode != "frontend_event":
                    continue
                item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
                if item.event_type == "agent_package_instance_updated":
                    latest_status = dict(item.payload or {})
                    self._instance_status_overrides[package_id] = latest_status
                elif item.event_type == "run_failed":
                    latest_status = self._publish_instance_status(
                        package_id=package_id,
                        package=package,
                        request_id=request_id,
                        status="failed",
                        ready=False,
                        stage="failed",
                        error=str(item.message or item.payload.get("message") or "initialize failed"),
                    )
                if self._emit is not None:
                    self._emit(item)
        except Exception as exc:
            if not environment_prepared:
                self._environment_preparation_errors[package_id] = f"{type(exc).__name__}: {exc}"
            latest_status = self._publish_instance_status(
                package_id=package_id,
                package=package,
                request_id=request_id,
                status="failed",
                ready=False,
                stage="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        return latest_status or self.package_instance_status(package_id)

    def _package_runtime_is_initialized(
        self,
        package_id: str,
        package: LoadedAgentPackage,
    ) -> bool:
        if not self._has_ready_runtime(package_id, package):
            return False
        status = self.package_instance_status(package_id)
        return bool(status.get("ready")) and status.get("status") == "ready"

    def shutdown_package_instance(
        self,
        package_id: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        self._close_package_containers(package_id)
        self._close_package_system_handles(package_id)
        status = self.package_instance_status(package_id)
        status = {**status, "status": "stopped", "ready": False}
        self._instance_status_overrides.pop(package_id, None)
        if self._emit is not None:
            self._emit(
                event(
                    "agent_package_instance_updated",
                    request_id=request_id,
                    mode="agent_package",
                    graph_id="agent_package_runtime",
                    producer_type="factory_runtime",
                    payload=status,
                )
            )
        return status

    def restart_package_instance(
        self,
        package_id: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        initialization_lock = self._package_initialization_lock(package_id)
        initialization_lock.acquire()
        try:
            package = self.load_package(package_id)
            self._publish_instance_status(
                package_id=package_id,
                package=package,
                request_id=request_id,
                status="initializing",
                ready=False,
                stage="restarting_runtime",
            )
            self._close_package_containers(package_id)
            self._close_package_system_handles(package_id)
            self._close_knowledge_runtime(package_id)
            self._instance_status_overrides.pop(package_id, None)
            package = self.load_package(package_id)
            return self._initialize_package_locked(
                package_id,
                package=package,
                request_id=request_id,
            )
        finally:
            initialization_lock.release()

    def shutdown_session_runtime(
        self,
        package_id: str,
        *,
        session_id: str,
    ) -> bool:
        del package_id, session_id
        # A session does not own a runtime process. The package runtime remains
        # alive so other sessions and persistent package state are unaffected.
        return False

    def scheduler_events(
        self,
        package_id: str,
        *,
        payload: dict[str, Any],
        request_id: str | None = None,
    ) -> Iterator[tuple[str, Any]]:
        package = self.load_package(package_id)
        command = {
            "type": "scheduler_manage",
            "request_id": request_id or uuid4().hex,
            "payload": dict(payload),
        }
        yield from self._runtime_events(package_id, package=package, command=command)

    def package_summary(self, package_id: str) -> dict[str, Any]:
        return self._package_summary(self._manifest_path(package_id))

    def update_context_config(
        self,
        package_id: str,
        *,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        package_dir = self.repository.package_dir(package_id)
        if not (package_dir / "agent_package.json").is_file():
            raise FileNotFoundError(f"agent package not found: {package_id}")
        AgentPackageConfigurationEditor().update_context_config(
            package_dir,
            config,
        )
        return self.package_summary(package_id)

    def update_scheduler_config(
        self,
        package_id: str,
        *,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        package_dir = self.repository.package_dir(package_id)
        if not (package_dir / "agent_package.json").is_file():
            raise FileNotFoundError(f"agent package not found: {package_id}")
        AgentPackageConfigurationEditor().update_scheduler_config(
            package_dir,
            config,
        )
        return self.package_summary(package_id)

    def update_model_overrides(
        self,
        package_id: str,
        *,
        bindings: dict[str, Any],
        tool_bindings: dict[str, Any],
    ) -> dict[str, Any]:
        package_dir = self.repository.package_dir(package_id)
        if not (package_dir / "agent_package.json").is_file():
            raise FileNotFoundError(f"agent package not found: {package_id}")
        AgentPackageConfigurationEditor().update_model_overrides(
            package_dir,
            bindings=bindings,
            tool_bindings=tool_bindings,
        )
        return self.package_summary(package_id)

    def delete_package(self, package_id: str) -> dict[str, Any]:
        manifest_path = self._manifest_path(package_id)
        if not self.repository.package_capabilities(manifest_path)["deletable"]:
            raise ValueError(f"built-in agent package cannot be deleted: {package_id}")
        self._close_package_containers(package_id)
        self._close_package_system_handles(package_id)
        self._close_knowledge_runtime(package_id)
        result = self.repository.delete_user_package(package_id)
        self._environment_preparation_errors.pop(package_id, None)
        result["deleted_resource_count"] = self.resource_store.delete_package(package_id)
        result["agent_registry_refresh"] = _refresh_agent_registry_index(package_id)
        return result

    def package_distribution_preview(self, package_id: str) -> dict[str, object]:
        return self.repository.distribution_preview(package_id)

    def export_package_archive(
        self,
        package_id: str,
        *,
        extension_overrides: dict[str, object] | None = None,
    ) -> Path:
        return self.repository.export_user_package_archive(
            package_id,
            extension_overrides=extension_overrides,
        )

    def install_package_archive(
        self,
        archive_path: str | Path,
        *,
        expected_sha256: str,
        expected_package_id: str,
        replace: bool,
        model_bindings: dict[str, str],
        model_tool_bindings: dict[str, str],
    ) -> dict[str, Any]:
        existing_manifest = self.repository.manifest_path(expected_package_id)
        if existing_manifest.is_file():
            self.shutdown_package_instance(expected_package_id)
            self._close_knowledge_runtime(expected_package_id)
        package = self.repository.install_user_package_archive(
            archive_path,
            expected_sha256=expected_sha256,
            expected_package_id=expected_package_id,
            replace=replace,
            prepare_package=lambda package_root: AgentPackageConfigurationEditor().rebind_models(
                package_root,
                bindings=dict(model_bindings),
                tool_bindings=dict(model_tool_bindings),
            ),
        )
        self._environment_preparation_errors.pop(expected_package_id, None)
        return self._package_summary(package.manifest_path)

    def list_sessions(self, package_id: str, *, include_internal: bool = False) -> list[dict[str, Any]]:
        package = self.load_package(package_id)
        return self._list_sessions_for_loaded_package(
            package_id,
            package,
            include_internal=include_internal,
        )

    def list_recent_sessions(self, *, limit: int = 5) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for package in self.list_packages():
            package_id = str(package.get("package_id") or "").strip()
            if not package_id:
                continue
            package_name = str(package.get("agent_name") or package.get("name") or package_id)
            try:
                package_sessions = self.list_sessions(package_id)
            except Exception as exc:
                logger.warning("Failed to list sessions for package %s: %s", package_id, exc)
                continue
            for session in package_sessions:
                item = dict(session)
                item["package_id"] = package_id
                item["package_name"] = package_name
                item["agent_name"] = package_name
                sessions.append(item)
        sessions.sort(key=_session_updated_sort_key, reverse=True)
        return sessions[: max(1, limit)]

    def load_session(self, package_id: str, session_id: str) -> dict[str, Any]:
        package = self.load_package(package_id)
        session = self._session_manager_for_package(package_id, package).load(session_id).model_dump(mode="json")
        return _hydrate_session_runtime_view(
            self._session_with_workspace(package_id, session)
        )

    def list_workspace_mounts(self, package_id: str, session_id: str) -> list[dict[str, object]]:
        workspace = self._workspace_for_session(package_id, session_id)
        return [
            workspace_mount_payload(mount, workdir_root=workspace.workdir)
            for mount in workspace.record.mounts
        ]

    def mount_workspace_directory(
        self,
        package_id: str,
        session_id: str,
        *,
        source_path: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace_for_session(package_id, session_id)
        service = WorkspaceMountService(workspace.workdir)
        mount, created = service.mount(
            source_path=source_path,
            name=name,
            existing=workspace.record.mounts,
        )
        if created:
            workspace.record.mounts.append(mount)
            try:
                WorkspaceStore().save(workspace.record)
            except Exception:
                service.unmount(mount)
                raise
        elif not service.ensure_projection(mount):
            raise ValueError(
                f"workspace mount projection is occupied by another entry: {mount.name}"
            )
        return {
            "package_id": package_id,
            "package_session_id": session_id,
            "mount": workspace_mount_payload(mount, workdir_root=workspace.workdir),
            "created": created,
        }

    def unmount_workspace_directory(
        self,
        package_id: str,
        session_id: str,
        mount_id: str,
    ) -> dict[str, Any]:
        workspace = self._workspace_for_session(package_id, session_id)
        normalized_mount_id = str(mount_id or "").strip()
        mount = next(
            (item for item in workspace.record.mounts if item.mount_id == normalized_mount_id),
            None,
        )
        if mount is None:
            raise FileNotFoundError(f"workspace mount not found: {normalized_mount_id}")
        service = WorkspaceMountService(workspace.workdir)
        service.unmount(mount)
        workspace.record.mounts = [
            item for item in workspace.record.mounts
            if item.mount_id != normalized_mount_id
        ]
        try:
            WorkspaceStore().save(workspace.record)
        except Exception:
            service.ensure_projection(mount)
            raise
        return {
            "package_id": package_id,
            "package_session_id": session_id,
            "mount_id": normalized_mount_id,
            "removed": True,
        }

    def workspace_mount_records(
        self,
        package_id: str,
        session_id: str,
    ) -> dict[str, WorkspaceMountRecord]:
        workspace = self._workspace_for_session(package_id, session_id)
        return {mount.name: mount for mount in workspace.record.mounts}

    def session_exists(self, package_id: str, session_id: str) -> bool:
        package = self.load_package(package_id)
        return self._session_manager_for_package(package_id, package).exists(session_id)

    def delete_session(
        self,
        package_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        cancelled_active_request_count = self.cancel_active_requests(
            reason="session_deleted",
            package_id=package_id,
            session_id=session_id,
        )
        manager = self._session_manager_for_package(package_id, package)
        record = manager.load_optional(session_id)
        if record is None:
            deleted_workdir = _delete_agent_session_workdir(package_id, session_id)
            return {
                "package_id": package_id,
                "session_id": session_id,
                "deleted": False,
                "missing": True,
                "deleted_trace_count": 0,
                "deleted_checkpoint_count": 0,
                "deleted_workdir": deleted_workdir,
                "cancelled_active_request_count": cancelled_active_request_count,
                "sessions": self._list_sessions_for_loaded_package(package_id, package),
                "recent_agent_sessions": self.list_recent_sessions(),
            }
        workspace = self._workspace_for_session(package_id, record.session_id)
        deleted_checkpoint_count = _delete_agent_session_checkpoint(
            package_id=package_id,
            package=package,
            session_id=record.session_id,
            thread_id=record.thread_id,
        )
        result = manager.delete(record.session_id)
        remaining_workspace_sessions = [
            item
            for item in manager.list_sessions(include_internal=True)
            if item.workspace_id == record.workspace_id
        ]
        deleted_workdir = False
        if workspace.record.mode == "isolated" and not remaining_workspace_sessions:
            _remove_session_workspace_mounts(
                workspace.record.mounts,
                workdir_root=workspace.workdir,
            )
            WorkspaceStore().delete(workspace.record.workspace_id, delete_files=True)
            deleted_workdir = True
        return {
            "package_id": package_id,
            "session_id": result.record.session_id,
            "deleted": True,
            "deleted_trace_count": result.deleted_trace_count,
            "deleted_checkpoint_count": deleted_checkpoint_count,
            "deleted_workdir": deleted_workdir,
            "cancelled_active_request_count": cancelled_active_request_count,
            "sessions": self._list_sessions_for_loaded_package(package_id, package),
            "recent_agent_sessions": self.list_recent_sessions(),
        }

    def workspace_roots(self, package_id: str, *, session_id: str | None = None) -> dict[str, Any]:
        package = self.load_package(package_id)
        return self.workspace.roots(package_id, package, session_id=session_id)

    def workspace_root_paths(self, package_id: str, *, session_id: str | None = None) -> dict[str, Path]:
        package = self.load_package(package_id)
        return workspace_roots(package_id, package, session_id=session_id)

    def list_workspace_entries(
        self,
        package_id: str,
        *,
        scope: str = "workdir",
        relative_path: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        return self.workspace.list_entries(
            package_id,
            package,
            scope=scope,
            relative_path=relative_path,
            session_id=session_id,
        )

    def read_workspace_file(
        self,
        package_id: str,
        *,
        scope: str = "workdir",
        relative_path: str,
        max_chars: int = 20000,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        return self.workspace.read_file(
            package_id,
            package,
            scope=scope,
            relative_path=relative_path,
            max_chars=max_chars,
            session_id=session_id,
        )

    def resolve_workspace_file(
        self,
        package_id: str,
        *,
        scope: str = "workdir",
        relative_path: str,
        session_id: str | None = None,
    ) -> Path:
        package = self.load_package(package_id)
        return self.workspace.resolve_file(
            package_id,
            package,
            scope=scope,
            relative_path=relative_path,
            session_id=session_id,
        )

    def extension_config_summary(self, package_id: str) -> dict[str, Any]:
        package = self.load_package(package_id)
        return self.extensions.summary(package_id, package)

    def system_extension_config_summary(self, resource_mode: str) -> dict[str, Any]:
        if resource_mode not in {"create_agent", "evolve_agent"}:
            raise ValueError(f"unsupported system extension resource mode: {resource_mode}")
        return self.extensions.system_summary(resource_mode)

    def extensions_manage(
        self,
        package_id: str,
        action: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        progress: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        result = self.extensions.manage(
            package_id,
            package,
            action,
            payload,
            request_id=request_id,
            progress=progress,
        )
        return result.payload

    def system_extensions_manage(
        self,
        resource_mode: str,
        action: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        progress: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        if resource_mode not in {"create_agent", "evolve_agent"}:
            raise ValueError(f"unsupported system extension resource mode: {resource_mode}")
        result = self.extensions.system_manage(
            resource_mode,
            action,
            payload,
            request_id=request_id,
            progress=progress,
        )
        return result.payload

    def cancel_extension_request(self, request_id: str | None) -> bool:
        return self.extensions.cancel_operation(request_id)

    def knowledge_runtime_for_package(
        self,
        package_id: str,
        *,
        background: bool = False,
    ) -> KnowledgeRuntime:
        package = self.load_package(package_id)
        runtime_root = _host_runtime_root(package_id)
        defaults = KnowledgeRuntimeConfig()
        knowledge_root = runtime_root / "knowledge"
        config = defaults.model_copy(
            update={
                "root": str(knowledge_root),
                "catalog_path": str(knowledge_root / "catalog" / "knowledge.sqlite"),
                "rag_store": defaults.rag_store.model_copy(
                    update={"path": str(knowledge_root / "catalog" / "knowledge_store.sqlite")}
                ),
            },
        )
        if not background:
            return build_knowledge_runtime(
                config=config,
                owner_type="agent",
                owner_id=package.assembly_spec.agent.id,
            ).runtime
        package_fingerprint = _runtime_fingerprint(package_id, package)
        with self._package_initialization_lock(package_id):
            with self._runtime_handle_lock:
                existing = self._knowledge_handles.get(package_id)
                if existing is not None and existing.package_fingerprint == package_fingerprint:
                    return existing.runtime
                stale = self._knowledge_handles.pop(package_id, None)
            if stale is not None:
                stale.close()
            assembly = build_knowledge_runtime(
                config=config,
                owner_type="agent",
                owner_id=package.assembly_spec.agent.id,
                event_sink=self._knowledge_event_sink(package_id),
            )
            runtime = assembly.runtime
            worker = assembly.ingestion_worker
            worker.start()
            with self._runtime_handle_lock:
                self._knowledge_handles[package_id] = KnowledgeRuntimeHandle(
                    runtime=runtime,
                    worker=worker,
                    package_fingerprint=package_fingerprint,
                )
            return runtime

    def _knowledge_event_sink(self, package_id: str) -> Callable[[dict[str, Any]], None]:
        def emit_knowledge(payload: dict[str, Any]) -> None:
            event_type = str(payload.get("event_type") or "").strip()
            if not event_type:
                return
            self.emit_frontend_event(
                event(
                    event_type,
                    request_id=None,
                    mode="agent_package",
                    graph_id="knowledge_ingestion",
                    producer_type="knowledge_runtime",
                    payload={"package_id": package_id, **payload},
                )
            )

        return emit_knowledge

    def _close_knowledge_runtime(self, package_id: str) -> None:
        with self._runtime_handle_lock:
            handle = self._knowledge_handles.pop(package_id, None)
        if handle is not None:
            handle.close()

    def knowledge_manage(self, package_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        runtime = self.knowledge_runtime_for_package(package_id, background=True)
        if action == "list_sources":
            return {"sources": [source.model_dump(mode="json") for source in runtime.list_sources()]}
        if action == "list_documents":
            return {
                "documents": [
                    document.model_dump(mode="json")
                    for document in runtime.list_documents(payload.get("source_id"))
                ]
            }
        if action == "search":
            results = runtime.search(
                query=str(payload.get("query") or ""),
                source_id=payload.get("source_id"),
                mode=str(payload.get("mode") or "auto"),
                top_k=int(payload.get("top_k") or 8),
            )
            return {"results": [result.model_dump(mode="json") for result in results]}
        if action == "open":
            return runtime.open(
                source_id=payload.get("source_id"),
                document_id=payload.get("document_id"),
                chunk_id=payload.get("chunk_id"),
            )
        if action == "read":
            return runtime.read(
                document_id=payload.get("document_id"),
                chunk_id=payload.get("chunk_id"),
                max_chars=payload.get("max_chars"),
            )
        if action == "prepare_source":
            source = _normalized_source_payload(payload.get("source") if isinstance(payload.get("source"), dict) else payload)
            preview = runtime.prepare_source(source)
            return {"preview": preview.model_dump(mode="json")}
        if action == "confirm_source":
            source = _normalized_source_payload(payload.get("source") if isinstance(payload.get("source"), dict) else payload)
            job = runtime.confirm_source(source)
            return {"job": job.model_dump(mode="json"), "sources": [item.model_dump(mode="json") for item in runtime.list_sources()]}
        if action == "remove_source":
            source_id = str(payload.get("source_id") or "")
            return {
                "source_id": source_id,
                "removed": runtime.remove_source(source_id),
                "sources": [item.model_dump(mode="json") for item in runtime.list_sources()],
            }
        if action == "reindex":
            source_id = str(payload.get("source_id") or "")
            job = runtime.reindex_source(source_id)
            return {
                "source_id": source_id,
                "job": job.model_dump(mode="json"),
                "sources": [item.model_dump(mode="json") for item in runtime.list_sources()],
            }
        raise ValueError(f"unsupported knowledge action: {action}")

    def ensure_session(
        self,
        package_id: str,
        *,
        session_id: str | None = None,
        first_user_input: str | None = None,
        session_kind: str = "normal",
        agent_group_id: str | None = None,
        visible_in_agent_session_list: bool | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        manager = self._session_manager_for_package(package_id, package)
        if session_id:
            try:
                return self._session_with_workspace(
                    package_id,
                    manager.load(session_id).model_dump(mode="json"),
                )
            except FileNotFoundError:
                pass
        workspace = self._resolve_workspace_for_new_session(
            package_id=package_id,
            workspace_id=workspace_id,
            title=first_user_input,
        )
        session = manager.create(
            agent_id=package.assembly_spec.agent.id,
            workspace_id=workspace.workspace_id,
            session_id=session_id,
            first_user_input=first_user_input,
            session_kind=session_kind,
            agent_group_id=agent_group_id,
            visible_in_agent_session_list=visible_in_agent_session_list,
        )
        return self._session_with_workspace(
            package_id,
            session.model_dump(mode="json"),
        )

    def run(self, package_id: str, *, user_input: str, session_id: str | None = None) -> AgentPackageRunResult:
        raise RuntimeError("AgentPackage host-process execution is disabled; use stream() for sandbox execution.")

    def stream(
        self,
        package_id: str,
        *,
        user_input: str,
        display_user_input: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        user_config: dict[str, Any] | None = None,
        runtime_request: dict[str, Any] | None = None,
        attachments: Any = None,
        message_metadata: dict[str, Any] | None = None,
        require_ready: bool = False,
        session_kind: str = "normal",
        agent_group_id: str | None = None,
        visible_in_agent_session_list: bool | None = None,
        workdir_root: Path | None = None,
        workspace_id: str | None = None,
    ) -> AgentPackageStreamRun:
        package = self.load_package(package_id)
        del require_ready
        resolved_request_id = request_id or uuid4().hex
        session_user_input = str(display_user_input or "").strip() or user_input
        session_manager = self._session_manager_for_package(package_id, package)
        if session_id:
            session = session_manager.load(session_id)
        else:
            workspace = self._resolve_workspace_for_new_session(
                package_id=package_id,
                workspace_id=workspace_id,
                title=session_user_input,
            )
            session = session_manager.create(
                agent_id=package.assembly_spec.agent.id,
                workspace_id=workspace.workspace_id,
                first_user_input=session_user_input,
                session_kind=session_kind,
                agent_group_id=agent_group_id,
                visible_in_agent_session_list=visible_in_agent_session_list,
            )
        if session_id and (
            session_kind != "normal"
            or agent_group_id
            or visible_in_agent_session_list is not None
        ):
            session = session_manager.update_metadata(
                session.session_id,
                session_kind=session_kind,
                agent_group_id=agent_group_id,
                visible_in_agent_session_list=visible_in_agent_session_list,
            )
        workspace = self._workspace_for_session(package_id, session.session_id)
        resolved_workdir_root = workdir_root or workspace.workdir
        runtime_workspace = _runtime_workspace_payload(
            package_id,
            resolved_workdir_root,
            workspace_id=session.workspace_id,
            mounts=workspace.record.mounts,
        )
        attachment_result = self._prepare_runtime_attachments(
            package_id=package_id,
            package=package,
            workdir_root=resolved_workdir_root,
            user_input=user_input,
            attachments=attachments,
        )
        session = session_manager.touch_turn(
            session.session_id,
            request_id=resolved_request_id,
            first_user_input=session_user_input,
            user_input=session_user_input,
            attachments=attachment_result.attachments,
            message_metadata=message_metadata,
            status="running",
        )
        request_policy = RuntimeRequestPolicy.from_payload(
            runtime_request,
            default=self.request_policy,
        )
        command = {
            "type": "run_message",
            "request_id": resolved_request_id,
            "payload": {
                "message": attachment_result.message,
                "session_id": session.session_id,
                "user_config": dict(user_config or {}),
                "attachments": attachment_result.attachments,
                "runtime_request": request_policy.as_payload(),
                "runtime_workspace": runtime_workspace,
            },
        }
        if _is_host_system_package(package):
            return AgentPackageStreamRun(
                package=package,
                session=self._session_with_workspace(package_id, session.model_dump(mode="json")),
                request_id=resolved_request_id,
                events=self._system_events(package_id, package=package, command=command, workdir_root=resolved_workdir_root),
            )
        return AgentPackageStreamRun(
            package=package,
            session=self._session_with_workspace(package_id, session.model_dump(mode="json")),
            request_id=resolved_request_id,
            events=self._container_events(package_id, package=package, command=command, workdir_root=resolved_workdir_root),
        )

    def _prepare_runtime_attachments(
        self,
        *,
        package_id: str,
        package: LoadedAgentPackage,
        workdir_root: Path,
        user_input: str,
        attachments: Any,
    ) -> AttachmentImportResult:
        attachment_scope = time_named_attachment_scope()
        if _is_host_system_package(package):
            runtime_workdir = str(workdir_root)
        else:
            runtime_workdir = str(workdir_root.resolve())
        runtime_path_root = workspace_attachment_runtime_root(runtime_workdir, attachment_scope)
        return import_runtime_attachments(
            user_input,
            attachments,
            storage_root=workspace_attachment_root(workdir_root) / attachment_scope,
            runtime_path_root=runtime_path_root,
            base_dir=project_root(),
            scope=attachment_scope,
        )

    def resume_stream(
        self,
        package_id: str,
        *,
        session_id: str,
        resume_payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        runtime_request: dict[str, Any] | None = None,
        workdir_root: Path | None = None,
    ) -> AgentPackageStreamRun:
        package = self.load_package(package_id)
        session = self._session_manager_for_package(package_id, package).load(session_id)
        workspace = self._workspace_for_session(package_id, session.session_id)
        resolved_workdir_root = workdir_root or workspace.workdir
        runtime_workspace = _runtime_workspace_payload(
            package_id,
            resolved_workdir_root,
            workspace_id=session.workspace_id,
            mounts=workspace.record.mounts,
        )
        request_policy = RuntimeRequestPolicy.from_payload(
            runtime_request,
            default=self.request_policy,
        )
        command = {
            "type": "resume_interrupt",
            "request_id": request_id or uuid4().hex,
            "payload": {
                "session_id": session_id,
                "resume_payload": resume_payload or {},
                "runtime_request": request_policy.as_payload(),
                "runtime_workspace": runtime_workspace,
            },
        }

        if _is_host_system_package(package):
            return AgentPackageStreamRun(
                package=package,
                session=self._session_with_workspace(package_id, session.model_dump(mode="json")),
                request_id=command["request_id"],
                events=self._system_events(package_id, package=package, command=command, workdir_root=resolved_workdir_root),
            )
        return AgentPackageStreamRun(
            package=package,
            session=self._session_with_workspace(package_id, session.model_dump(mode="json")),
            request_id=command["request_id"],
            events=self._container_events(package_id, package=package, command=command, workdir_root=resolved_workdir_root),
        )

    def finish_session_turn(
        self,
        package_id: str,
        *,
        session_id: str,
        request_id: str | None = None,
        final_answer: str | None,
        reasoning_content: str | None = None,
        status: str,
        tool_activities: list[dict[str, Any]] | None = None,
        trace_ref: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        session = self._session_manager_for_package(package_id, package).finish_turn(
            session_id,
            request_id=request_id,
            final_answer=final_answer,
            reasoning_content=reasoning_content,
            status=status,
            tool_activities=tool_activities,
            trace_ref=trace_ref,
        )
        return session.model_dump(mode="json")

    def _package_summary(self, manifest_path: Path) -> dict[str, Any]:
        package_id = manifest_path.parent.name
        package_origin = self.repository.package_origin(manifest_path)
        package_capabilities = self.repository.package_capabilities(manifest_path)
        try:
            package = self.repository.load_manifest(manifest_path)
            report = _read_json_object(manifest_path.parent / "package_report.json")
            sessions = self._list_sessions_for_loaded_package(package_id, package)
            detail = _package_detail_summary(self, package_id=package_id, package=package)
            return {
                "package_id": package_id,
                "package_path": str(manifest_path.parent),
                "manifest_path": str(manifest_path),
                "package_origin": package_origin,
                "is_builtin": package_origin == "system",
                "capabilities": package_capabilities,
                "factory_run_id": package.manifest.factory_run_id,
                "agent_id": package.assembly_spec.agent.id,
                "agent_name": package.assembly_spec.agent.name,
                "agent_description": package.assembly_spec.agent.description,
                "runtime_pattern_id": package.assembly_spec.runtime.pattern_id,
                "status": str(report.get("status") or "available"),
                "updated_at": _path_updated_at(manifest_path.parent),
                "tool_count": len(package.assembly_spec.tools),
                "session_count": len(sessions),
                "model_contract": _model_contract_summary(package),
                "context_contract": _context_contract_summary(manifest_path.parent),
                "scheduler_contract": _scheduler_contract_summary(package),
                "resources": self.resource_status(package_id),
                "environment": _environment_summary(
                    manifest_path.parent,
                    preparation_error=self._environment_preparation_errors.get(package_id),
                ),
                "extensions": _extensions_summary(package_id, package=package),
                **detail,
            }
        except Exception as exc:
            return {
                "package_id": package_id,
                "package_path": str(manifest_path.parent),
                "manifest_path": str(manifest_path),
                "package_origin": package_origin,
                "is_builtin": package_origin == "system",
                "capabilities": package_capabilities,
                "status": "invalid",
                "runtime_pattern_id": None,
                "updated_at": _path_updated_at(manifest_path.parent),
                "error": f"{type(exc).__name__}: {exc}",
                "model_contract": {"version": "", "bindings": {}, "tool_bindings": {}},
                "context_contract": _context_contract_summary(manifest_path.parent),
                "scheduler_contract": {"version": "", "enabled": False, "config": {}},
                "extensions": _extensions_summary(package_id),
                "tools": [],
                "mcp_servers": [],
                "skills": [],
                "knowledge_sources": [],
            }

    def _session_manager_for_package(self, package_id: str, package: LoadedAgentPackage) -> AgentSessionManager:
        return AgentSessionManager(
            AgentSessionConfig(root=_host_runtime_root(package_id) / "sessions")
        )

    def _resolve_workspace_for_new_session(
        self,
        *,
        package_id: str,
        workspace_id: str | None,
        title: str | None,
    ) -> WorkspaceRecord:
        store = WorkspaceStore()
        identifier = str(workspace_id or "").strip()
        if identifier:
            record = store.load(identifier)
            if record.mode != "project":
                record = store.update(identifier, mode="project")
            return record
        return store.create(
            title=title,
            mode="isolated",
            owner_package_id=package_id,
        )

    def _list_sessions_for_loaded_package(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        *,
        include_internal: bool = False,
    ) -> list[dict[str, Any]]:
        manager = self._session_manager_for_package(package_id, package)
        return [
            {
                **self._session_with_workspace(
                    package_id,
                    record.model_dump(mode="json"),
                ),
                "package_id": package_id,
            }
            for record in manager.list_sessions(
                agent_id=package.assembly_spec.agent.id,
                include_internal=include_internal,
            )
        ]

    def _session_with_workspace(
        self,
        package_id: str,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        hydrated = dict(session)
        session_id = str(hydrated.get("session_id") or "").strip()
        if not session_id:
            return hydrated
        workspace = self._workspace_for_session(package_id, session_id)
        hydrated["workspace"] = {
            "workspace_id": workspace.record.workspace_id,
            "title": workspace.record.title,
            "mode": workspace.record.mode,
            "root_kind": workspace.record.root_kind,
            "workdir_root": str(workspace.workdir),
        }
        return hydrated

    def close_all(self) -> None:
        for package_id in list(self._knowledge_handles):
            self._close_knowledge_runtime(package_id)
        for runtime_key in list(self._containers):
            self._close_container(runtime_key)
        for runtime_key in list(self._system_handles):
            self._close_system(runtime_key)
        self._mcp_gateways.close_all()
        self._skillhub_gateways.close_all()

    def cancel_active_requests(
        self,
        *,
        reason: str = "user_cancelled",
        request_id: str | None = None,
        package_id: str | None = None,
        session_id: str | None = None,
    ) -> int:
        cancelled = 0
        target_package_id = str(package_id or "").strip()
        container_items = [
            (key, handle)
            for key, handle in self._containers.items()
            if not target_package_id or handle.package_id == target_package_id
        ]
        system_items = [
            (key, handle)
            for key, handle in self._system_handles.items()
            if not target_package_id or handle.package_id == target_package_id
        ]
        for _, handle in container_items:
            cancelled += handle.cancel_active_requests(
                reason=reason,
                request_id=request_id,
                session_id=session_id,
            )
        for _, handle in system_items:
            cancelled += handle.cancel_active_requests(
                reason=reason,
                request_id=request_id,
                session_id=session_id,
            )
        return cancelled

    def _system_events(
        self,
        package_id: str,
        *,
        package: LoadedAgentPackage,
        command: dict[str, Any],
        workdir_root: Path | None = None,
    ) -> Iterator[tuple[str, Any]]:
        request_id = str(command.get("request_id") or uuid4().hex)
        command["request_id"] = request_id
        runtime_key = _runtime_handle_key(package_id, command)
        will_start = not self._has_reusable_system_handle(runtime_key, package)
        if will_start:
            yield "frontend_event", node_event(
                request_id,
                "node_started",
                node_id="runtime_container",
                payload={
                    "package_id": package_id,
                    "backend": "host",
                    "status": "preflight",
                    "status_key": "runtime_initialization",
                },
            )
        try:
            handle = self._system_handle(
                package_id,
                package,
                runtime_key=runtime_key,
                workdir_root=workdir_root,
            )
            if handle.startup_payload is not None:
                yield "frontend_event", node_event(
                    request_id,
                    "node_completed",
                    node_id="runtime_container",
                    payload=handle.startup_payload,
                )
                handle.startup_payload = None
        except Exception as exc:
            failure_payload = {
                "where": "system_package.launch",
                "why": "host_runtime_start_failed",
                "message": f"{type(exc).__name__}: {exc}",
                "suggested_action": "Check the SystemPackage manifest, contracts, and runtime paths.",
            }
            if will_start:
                yield "frontend_event", node_event(
                    request_id,
                    "node_failed",
                    node_id="runtime_container",
                    payload=failure_payload,
                    severity="error",
                )
            yield "frontend_event", run_failed_event(request_id, failure_payload)
            return
        yield from _scoped_runtime_events(handle.send(command), package_id=package_id)

    def _container_events(
        self,
        package_id: str,
        *,
        package: LoadedAgentPackage,
        command: dict[str, Any],
        workdir_root: Path | None = None,
    ) -> Iterator[tuple[str, Any]]:
        request_id = str(command.get("request_id") or uuid4().hex)
        command["request_id"] = request_id
        runtime_key = _runtime_handle_key(package_id, command)
        will_start = not self._has_reusable_container(runtime_key, package)
        if will_start:
            yield "frontend_event", node_event(
                request_id,
                "node_started",
                node_id="runtime_container",
                payload={
                    "package_id": package_id,
                    "backend": "local",
                    "status": "preflight",
                    "status_key": "runtime_initialization",
                },
            )
        try:
            handle = self._container(
                package_id,
                package,
                runtime_key=runtime_key,
                workdir_root=workdir_root,
            )
            if handle.startup_payload is not None:
                yield "frontend_event", node_event(
                    request_id,
                    "node_completed",
                    node_id="runtime_container",
                    payload=handle.startup_payload,
                )
                handle.startup_payload = None
        except AgentRuntimeLaunchError as exc:
            if will_start:
                yield "frontend_event", node_event(
                    request_id,
                    "node_failed",
                    node_id="runtime_container",
                    payload=exc.payload,
                    severity="error",
                )
            yield "frontend_event", run_failed_event(request_id, exc.payload)
            return
        except Exception as exc:
            failure_payload = {
                "where": "agent_runtime.launch",
                "why": "local_runtime_start_failed",
                "message": f"{type(exc).__name__}: {exc}",
                "suggested_action": "Check the local runtime, dependency lock, and runtime contract.",
            }
            if will_start:
                yield "frontend_event", node_event(
                    request_id,
                    "node_failed",
                    node_id="runtime_container",
                    payload=failure_payload,
                    severity="error",
                )
            yield "frontend_event", run_failed_event(
                request_id,
                failure_payload,
            )
            return
        try:
            yield from _scoped_runtime_events(handle.send(command), package_id=package_id)
        except Exception:
            self._close_container(runtime_key)
            raise

    def _runtime_events(
        self,
        package_id: str,
        *,
        package: LoadedAgentPackage,
        command: dict[str, Any],
    ) -> Iterator[tuple[str, Any]]:
        if _is_host_system_package(package):
            yield from self._system_events(package_id, package=package, command=command)
            return
        yield from self._container_events(package_id, package=package, command=command)

    def _instance_status_payload(
        self,
        *,
        package_id: str,
        package: LoadedAgentPackage,
        status: str,
        ready: bool,
        stage: str | None = None,
        detail: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        backend = "host" if _is_host_system_package(package) else "local"
        payload: dict[str, Any] = {
            "package_id": package_id,
            "agent_id": package.assembly_spec.agent.id,
            "agent_name": package.assembly_spec.agent.name,
            "backend": backend,
            "status": status,
            "ready": ready,
            "runtime_root": str(_host_runtime_root(package_id)),
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }
        if error:
            payload["error"] = error
        if stage:
            payload["stage"] = stage
        if detail:
            payload["detail"] = detail
        return payload

    def _publish_instance_status(
        self,
        *,
        package_id: str,
        package: LoadedAgentPackage,
        request_id: str | None,
        status: str,
        ready: bool,
        stage: str | None = None,
        detail: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload = self._instance_status_payload(
            package_id=package_id,
            package=package,
            status=status,
            ready=ready,
            stage=stage,
            detail=detail,
            error=error,
        )
        self._instance_status_overrides[package_id] = payload
        if self._emit is not None:
            self._emit(
                event(
                    "agent_package_instance_updated",
                    request_id=request_id,
                    mode="agent_package",
                    graph_id="agent_package_runtime",
                    producer_type="factory_runtime",
                    severity="error" if error else None,
                    payload=payload,
                )
            )
        return payload

    def _container(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        *,
        runtime_key: str,
        workdir_root: Path | None = None,
    ) -> "NativeAgentRuntimeHandle":
        fingerprint = _runtime_fingerprint(package_id, package)
        with self._runtime_handle_lock:
            existing = self._containers.get(runtime_key)
            if (
                existing is not None
                and existing.is_running
                and existing.package_fingerprint == fingerprint
                and not existing.is_idle(self.idle_timeout_seconds)
            ):
                return existing
            self._close_container(runtime_key)
            handle = self._create_container_handle(
                package_id,
                package,
                fingerprint,
                runtime_key,
                workdir_root,
            )
            self._containers[runtime_key] = handle
            return handle

    def _create_container_handle(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        fingerprint: str,
        runtime_instance_id: str,
        workdir_root: Path | None,
    ) -> "NativeAgentRuntimeHandle":
        """Create the package's single logical runtime bridge."""
        workspace = _package_runtime_workspace(package_id).ensure()
        runtime_root = workspace.root
        artifacts_root = workspace.artifacts
        workdir_root = (workdir_root or workspace.workdir).expanduser().resolve()
        extension_root = _extension_root_for_package(package_id, package)
        for path in (artifacts_root, workdir_root, runtime_root, extension_root):
            path.mkdir(parents=True, exist_ok=True)
        mcp_gateway = self._mcp_gateways.ensure_gateway(
            _load_extension_bundle(extension_root, package=package).mcp_servers
        )
        try:
            skillhub_gateway = self._skillhub_gateways.ensure_gateway(
                default_extension_registry_root()
            )
            plan = self.launcher.prepare(
                package=package,
                runtime_root=runtime_root,
                artifacts_root=artifacts_root,
                workdir_root=workdir_root,
                runtime_instance_id=runtime_instance_id,
                extension_root=extension_root,
                mcp_gateway_url=mcp_gateway.host_url if mcp_gateway is not None else None,
                skillhub_gateway_url=skillhub_gateway.host_url,
            )

            handle = NativeAgentRuntimeHandle(
                package_id=package_id,
                package_fingerprint=fingerprint,
                idle_timeout_seconds=self.idle_timeout_seconds,
                request_policy=self.request_policy,
                bridge_startup_timeout_seconds=self.bridge_startup_timeout_seconds,
                command=plan.command,
                environment=plan.environment,
                emit=self._emit,
            )
        except Exception:
            if mcp_gateway is not None:
                self._mcp_gateways.release_gateway(mcp_gateway.key)
            raise
        if mcp_gateway is not None:
            self._container_mcp_gateway_keys[runtime_instance_id] = mcp_gateway.key
        handle.startup_payload = {
            "package_id": package_id,
            "status": "running",
            "pid": handle.process.pid,
            "runtime_type": "local",
            "extension_root": str(plan.extension_root),
            "preflight": plan.preflight,
            "isolation": plan.isolation,
        }
        return handle

    def _system_handle(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        *,
        runtime_key: str,
        workdir_root: Path | None = None,
    ) -> "SystemPackageRuntimeHandle":
        with self._runtime_handle_lock:
            existing = self._system_handles.get(runtime_key)
            fingerprint = _runtime_fingerprint(package_id, package)
            if (
                existing is not None
                and existing.is_running
                and existing.package_fingerprint == fingerprint
                and not existing.is_idle(self.idle_timeout_seconds)
            ):
                return existing
            self._close_system(runtime_key)
            workspace = _package_runtime_workspace(package_id).ensure()
            runtime_root = workspace.root
            artifacts_root = workspace.artifacts
            workdir_root = (workdir_root or workspace.workdir).expanduser().resolve()
            extension_root = _extension_root_for_package(package_id, package)
            for path in (artifacts_root, workdir_root, runtime_root, extension_root):
                path.mkdir(parents=True, exist_ok=True)
            host_package = host_runtime_package_view(
                package,
                runtime_root=runtime_root,
                artifacts_root=artifacts_root,
                workdir_root=workdir_root,
                extension_root=extension_root,
            )
            handle = SystemPackageRuntimeHandle(
                package_id=package_id,
                package=host_package,
                package_fingerprint=fingerprint,
                runtime_root=runtime_root,
                workdir_root=workdir_root,
                runtime_instance_id=runtime_key,
                instance_extension_root=extension_root,
                idle_timeout_seconds=self.idle_timeout_seconds,
                request_policy=self.request_policy,
                producer_type="factory_runtime" if _is_system_package(package) else "agent_runtime_host",
                emit=self._emit,
            )
            handle.startup_payload = {
                "status": "running",
                "backend": "host",
                "package_id": package_id,
                "runtime_root": str(runtime_root),
                "artifact_root": str(artifacts_root),
                "workdir": str(workdir_root),
                "extension_root": str(extension_root),
            }
            self._system_handles[runtime_key] = handle
            return handle

    def _has_reusable_container(self, runtime_key: str, package: LoadedAgentPackage) -> bool:
        existing = self._containers.get(runtime_key)
        if existing is None or not existing.is_running:
            return False
        if existing.package_fingerprint != _runtime_fingerprint(existing.package_id, package):
            return False
        return not existing.is_idle(self.idle_timeout_seconds)

    def _has_reusable_system_handle(self, runtime_key: str, package: LoadedAgentPackage) -> bool:
        existing = self._system_handles.get(runtime_key)
        if existing is None or not existing.is_running:
            return False
        if existing.package_fingerprint != _runtime_fingerprint(existing.package_id, package):
            return False
        return not existing.is_idle(self.idle_timeout_seconds)

    def _has_ready_runtime(self, package_id: str, package: LoadedAgentPackage) -> bool:
        if _is_host_system_package(package):
            return any(
                self._has_reusable_system_handle(key, package)
                for key, handle in self._system_handles.items()
                if handle.package_id == package_id
            )
        return any(
            self._has_reusable_container(key, package)
            for key, handle in self._containers.items()
            if handle.package_id == package_id
        )

    def _close_container(self, runtime_key: str) -> None:
        with self._runtime_handle_lock:
            handle = self._containers.pop(runtime_key, None)
            gateway_key = self._container_mcp_gateway_keys.pop(runtime_key, None)
            package_id = handle.package_id if handle is not None else _runtime_key_package_id(runtime_key)
            self._instance_status_overrides.pop(package_id, None)
            try:
                if handle is not None:
                    handle.close()
            finally:
                if gateway_key is not None:
                    self._mcp_gateways.release_gateway(gateway_key)

    def _close_system(self, runtime_key: str) -> None:
        with self._runtime_handle_lock:
            handle = self._system_handles.pop(runtime_key, None)
            package_id = handle.package_id if handle is not None else _runtime_key_package_id(runtime_key)
            self._instance_status_overrides.pop(package_id, None)
            if handle is not None:
                handle.close()

    def _close_package_containers(self, package_id: str) -> None:
        for runtime_key, handle in list(self._containers.items()):
            if handle.package_id == package_id:
                self._close_container(runtime_key)

    def _close_package_system_handles(self, package_id: str) -> None:
        for runtime_key, handle in list(self._system_handles.items()):
            if handle.package_id == package_id:
                self._close_system(runtime_key)

    def _runtime_handles_for_package(self, package_id: str, *, backend: str) -> list[Any]:
        handles = self._system_handles if backend == "host" else self._containers
        return [handle for handle in handles.values() if handle.package_id == package_id]

    def _manifest_path(self, package_id: str) -> Path:
        return self.repository.manifest_path(package_id)

    def _package_dir(self, package_id: str, *, include_system_packages: bool = True) -> Path:
        return self.repository.package_dir(package_id, include_system_packages=include_system_packages)

def _scoped_runtime_events(
    events: Iterator[tuple[str, Any]],
    *,
    package_id: str,
) -> Iterator[tuple[str, Any]]:
    for stream_mode, chunk in events:
        if stream_mode == "frontend_event":
            yield stream_mode, _scoped_runtime_event(chunk, package_id=package_id)
            continue
        yield stream_mode, chunk


def _scoped_runtime_event(chunk: Any, *, package_id: str) -> FactoryFrontendEvent:
    item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
    payload = item.payload if isinstance(item.payload, dict) else None
    if payload is None:
        return item
    return item.model_copy(update={"payload": {**payload, "package_id": package_id}})


def _runtime_handle_key(package_id: str, command: dict[str, Any]) -> str:
    payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    runtime_workspace = (
        payload.get("runtime_workspace")
        if isinstance(payload.get("runtime_workspace"), dict)
        else {}
    )
    workspace_id = str(runtime_workspace.get("workspace_id") or "").strip()
    return f"{package_id}:{workspace_id}" if workspace_id else package_id


def _runtime_workspace_payload(
    package_id: str,
    workdir_root: Path,
    *,
    workspace_id: str | None = None,
    mounts: list[WorkspaceMountRecord] | None = None,
) -> dict[str, Any]:
    del package_id, workdir_root
    return {
        "scope": "",
        **({"workspace_id": workspace_id} if workspace_id else {}),
        "mounts": [
            {
                "name": mount.name,
                "source_path": mount.source_path,
            }
            for mount in mounts or []
        ],
    }


def _runtime_key_package_id(runtime_key: str) -> str:
    return runtime_key.split(":", 1)[0]


def _package_fingerprint(package: LoadedAgentPackage) -> str:
    digest = hashlib.sha256()
    digest.update(str(package.package_root.resolve()).encode("utf-8"))
    _hash_tree(digest, package.package_root)
    if _is_system_package(package):
        extension_root = _extension_root_for_package(package.package_root.name, package)
        if extension_root.resolve() != package.package_root.resolve():
            _hash_tree(digest, extension_root)
    if _is_host_system_package(package):
        digest.update(b"host-system-package")
    else:
        lock = EnvironmentResolver().read_lock(package.package_root)
        digest.update(str(lock.get("image_digest") or lock.get("image") or "").encode("utf-8"))
    return digest.hexdigest()


def _runtime_fingerprint(package_id: str, package: LoadedAgentPackage) -> str:
    digest = hashlib.sha256()
    digest.update(_package_fingerprint(package).encode("utf-8"))
    extension_root = _extension_root_for_package(package_id, package)
    digest.update(b"runtime-extension-root")
    digest.update(str(extension_root.resolve()).encode("utf-8"))
    _hash_tree(digest, extension_root)
    extension_bundle = _load_extension_bundle(extension_root, package=package)
    digest.update(b"resolved-extension-config")
    digest.update(
        json.dumps(
            {
                "mcp_servers": extension_bundle.mcp_servers.model_dump(mode="json"),
                "skills": extension_bundle.enabled_skills.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return digest.hexdigest()


def _environment_summary(package_root: Path, *, preparation_error: str | None = None) -> dict[str, Any]:
    try:
        lock = EnvironmentResolver().read_lock(package_root)
        pool = lock.get("pool") if isinstance(lock.get("pool"), dict) else {}
        return {
            "status": lock.get("status"),
            "image": lock.get("image"),
            "image_digest": lock.get("image_digest"),
            "platform": lock.get("platform"),
            "dependency_pool": {
                "python_entry_count": len(pool.get("python_entries") or []),
                "system_entry_count": len(pool.get("system_entries") or []),
                "has_npm_profile": bool(pool.get("npm_profile")),
            },
            "verified_at": lock.get("verified_at"),
        }
    except Exception as exc:
        return {
            "status": "failed" if preparation_error else "missing",
            "error": preparation_error or f"{type(exc).__name__}: {exc}",
        }


def _hash_tree(digest: "hashlib._Hash", root: Path) -> None:
    if not root.exists():
        digest.update(f"missing:{root}".encode("utf-8"))
        return
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path
        digest.update(str(relative).encode("utf-8"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(str(stat.st_size).encode("ascii"))


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _delete_agent_session_checkpoint(
    *,
    package_id: str,
    package: LoadedAgentPackage,
    session_id: str,
    thread_id: str,
) -> int:
    path = _host_runtime_root(package_id) / "checkpoints" / "agent.sqlite"
    return 1 if delete_sqlite_checkpoint_thread(path, thread_id) else 0


def _delete_agent_session_workdir(package_id: str, session_id: str) -> bool:
    path = _host_session_workdir(package_id, session_id)
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True


def _remove_session_workspace_mounts(
    mounts: list[WorkspaceMountRecord],
    *,
    workdir_root: Path,
) -> None:
    service = WorkspaceMountService(workdir_root)
    for mount in mounts:
        service.unmount(mount)


def _model_contract_summary(package: LoadedAgentPackage) -> dict[str, Any]:
    contract = package.contracts.get("model") if isinstance(package.contracts, dict) else None
    if not isinstance(contract, dict):
        return {"version": "", "bindings": {}, "tool_bindings": {}}
    config = contract.get("config") if isinstance(contract.get("config"), dict) else {}
    bindings = config.get("bindings") if isinstance(config.get("bindings"), dict) else {}
    tool_bindings = config.get("tool_bindings") if isinstance(config.get("tool_bindings"), dict) else {}
    public_bindings: dict[str, dict[str, Any]] = {}
    for role, binding in bindings.items():
        if not isinstance(binding, dict):
            continue
        public_bindings[str(role)] = {
            "profile_id": str(binding.get("profile_id") or ""),
            "source": str(binding.get("source") or "model_pool"),
            "selection_source": str(binding.get("selection_source") or ""),
            "reason": str(binding.get("reason") or ""),
            "required_capabilities": binding.get("required_capabilities") if isinstance(binding.get("required_capabilities"), dict) else {},
            "overrides": binding.get("overrides") if isinstance(binding.get("overrides"), dict) else {},
        }
    public_tool_bindings: dict[str, dict[str, Any]] = {}
    for tool_id, binding in tool_bindings.items():
        if not isinstance(binding, dict):
            continue
        public_tool_bindings[str(tool_id)] = {
            "profile_id": str(binding.get("profile_id") or ""),
            "source": str(binding.get("source") or "model_pool"),
            "capability": str(binding.get("capability") or ""),
            "selection_source": str(binding.get("selection_source") or ""),
            "reason": str(binding.get("reason") or ""),
            "description": str(binding.get("description") or ""),
            "required_capabilities": binding.get("required_capabilities") if isinstance(binding.get("required_capabilities"), dict) else {},
            "overrides": binding.get("overrides") if isinstance(binding.get("overrides"), dict) else {},
        }
    return {
        "version": str(contract.get("version") or ""),
        "bindings": public_bindings,
        "tool_bindings": public_tool_bindings,
    }


def _context_contract_summary(package_root: Path) -> dict[str, Any]:
    contract_path = package_root / "contracts" / "context.json"
    resolved = _resolved_main_model_for_package(package_root)
    settings = resolved.settings if resolved is not None else None
    fallback_limits = model_context_limits(model_role="main")
    base = {
        "version": "",
        "enabled": False,
        "config": {},
        "context_window_tokens": getattr(settings, "max_input_tokens", None) or fallback_limits.context_window_tokens,
        "context_window_tokens_source": "model_profile" if settings is not None else "system_default",
        "compression_threshold_tokens": (
            getattr(settings, "compression_trigger_tokens", None)
            or fallback_limits.compression_trigger_tokens
        ),
        "compression_threshold_tokens_source": "model_profile" if settings is not None else "system_default",
        "model_profile_id": getattr(settings, "profile_id", None),
    }
    if not contract_path.is_file():
        return base
    try:
        document = _read_json_object(contract_path)
        validated = ContextContract.model_validate(document)
    except Exception as exc:
        return {**base, "error": f"{type(exc).__name__}: {exc}"}
    config = validated.config
    compression_override = config.default_policy.compression.trigger_token_threshold
    context_window_override = config.context_window_tokens
    effective_limits = context_limits_with_overrides(
        ModelContextLimits(
            context_window_tokens=int(base["context_window_tokens"]),
            compression_trigger_tokens=int(base["compression_threshold_tokens"]),
        ),
        context_window_tokens=context_window_override,
        compression_trigger_tokens=compression_override,
    )
    compression_source = (
        "agent_override"
        if compression_override is not None
        else (
            "agent_window_limit"
            if effective_limits.compression_trigger_tokens != base["compression_threshold_tokens"]
            else base["compression_threshold_tokens_source"]
        )
    )
    return {
        **base,
        "version": validated.version,
        "enabled": validated.enabled and config.enabled,
        "config": config.model_dump(mode="json", exclude_none=False),
        "context_window_tokens": effective_limits.context_window_tokens,
        "context_window_tokens_source": "agent_override" if context_window_override is not None else base["context_window_tokens_source"],
        "compression_threshold_tokens": effective_limits.compression_trigger_tokens,
        "compression_threshold_tokens_source": compression_source,
    }


def _scheduler_contract_summary(package: LoadedAgentPackage) -> dict[str, Any]:
    contract = package.contracts.get("scheduler") if isinstance(package.contracts, dict) else None
    if not isinstance(contract, dict):
        return {"version": "", "enabled": False, "config": {}}
    return {
        "version": str(contract.get("version") or ""),
        "enabled": bool(contract.get("enabled", True)),
        "config": contract.get("config") if isinstance(contract.get("config"), dict) else {},
    }


def _resolved_main_model_for_package(package_root: Path):
    contract_path = package_root / "contracts" / "model.json"
    if contract_path.is_file():
        try:
            document = _read_json_object(contract_path)
            config = document.get("config") if isinstance(document.get("config"), dict) else {}
            bindings = config.get("bindings") if isinstance(config.get("bindings"), dict) else {}
            main = bindings.get("main")
            if isinstance(main, dict):
                binding = ModelProfileBinding.model_validate(main)
                if binding.source != "runtime":
                    return resolve_chat_model_binding(binding, role="main")
        except Exception:
            pass
    try:
        return resolve_available_chat_model("main")
    except Exception:
        return None


def _hydrate_session_runtime_view(session: dict[str, Any]) -> dict[str, Any]:
    hydrated = dict(session)
    trace_records = _session_trace_records(hydrated)
    if not trace_records:
        return hydrated
    latest_context = _latest_trace_event_payload(trace_records, "context_window_updated")
    if latest_context:
        hydrated["context_window"] = latest_context
    latest_plan = _latest_trace_event_payload(trace_records, "plan_updated")
    if latest_plan:
        hydrated["current_plan"] = latest_plan
    return hydrated


def _refresh_agent_registry_index(package_id: str) -> dict[str, Any]:
    try:
        return refresh_agent_registry_index(package_id)
    except Exception as exc:
        return {"status": "failed", "message": f"{type(exc).__name__}: {exc}"}


def _session_trace_records(session: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    runtime_refs = session.get("runtime_refs") if isinstance(session.get("runtime_refs"), dict) else {}
    default_trace_root = _trace_root_from_ref(runtime_refs)
    turns = session.get("turns") if isinstance(session.get("turns"), list) else []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        trace_ref = turn.get("trace_ref") if isinstance(turn.get("trace_ref"), dict) else {}
        trace_id = str(trace_ref.get("trace_id") or "").strip()
        if not trace_id or not _safe_path_id(trace_id):
            continue
        trace_root = _trace_root_from_ref(trace_ref) or default_trace_root
        if trace_root is None:
            continue
        records.extend(_read_trace_jsonl(trace_root / "runs" / trace_id / "trace.jsonl"))
    return records


def _latest_trace_event_payload(records: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for record in reversed(records):
        if record.get("event_type") != event_type:
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        return {
            **payload,
            "updated_at": record.get("created_at"),
            "trace_id": record.get("trace_id"),
            "run_id": record.get("run_id"),
        }
    return None


def _read_trace_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _trace_root_from_ref(ref: dict[str, Any]) -> Path | None:
    value = str(ref.get("trace_root") or ref.get("trace") or "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def _safe_path_id(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"-", "_"} for char in value)


def _package_detail_summary(
    manager: AgentPackageRuntimeManager,
    *,
    package_id: str,
    package: LoadedAgentPackage,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "tools": [_public_package_tool(spec) for spec in package.assembly_spec.tools],
        "mcp_servers": [],
        "skills": [],
        "knowledge_sources": [],
    }
    detail.update(_package_extension_detail(package_id=package_id, package=package))
    detail.update(_package_knowledge_detail(manager, package_id=package_id))
    return detail


def _package_knowledge_detail(manager: AgentPackageRuntimeManager, *, package_id: str) -> dict[str, Any]:
    try:
        runtime = manager.knowledge_runtime_for_package(package_id)
        sources = runtime.list_sources()
        document_counts = {
            source.source_id: len(runtime.list_documents(source.source_id))
            for source in sources
        }
        return {
            "knowledge_sources": [
                _public_knowledge_source(
                    source.model_dump(mode="json"),
                    document_count=document_counts.get(source.source_id),
                )
                for source in sources
            ],
        }
    except Exception as exc:
        return {
            "knowledge_sources": [],
            "knowledge_error": f"{type(exc).__name__}: {exc}",
        }


def _public_package_tool(spec: Any) -> dict[str, Any]:
    return {
        "kind": "package_tool",
        "id": str(getattr(spec, "id", "") or ""),
        "name": _humanize_identifier(str(getattr(spec, "id", "") or "")) or "Package Tool",
        "description": str(getattr(spec, "description", "") or ""),
        "risk_level": str(getattr(spec, "risk_level", "") or "low"),
        "concurrent": bool(getattr(spec, "concurrent", True)),
    }


def _public_knowledge_source(source: dict[str, Any], *, document_count: int | None = None) -> dict[str, Any]:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    return {
        "source_id": source.get("source_id"),
        "name": str(source.get("display_name") or source.get("name") or source.get("source_id") or "知识源"),
        "kind": source.get("source_type"),
        "status": source.get("status"),
        "mode": source.get("mount_mode"),
        "uri": source.get("original_uri") or source.get("uri"),
        "updated_at": source.get("updated_at"),
        "document_count": document_count if document_count is not None else metadata.get("document_count"),
        "sample_titles": metadata.get("sample_titles") if isinstance(metadata.get("sample_titles"), list) else [],
    }


def _session_updated_sort_key(session: dict[str, Any]) -> str:
    return str(session.get("updated_at") or session.get("created_at") or "")


def _normalized_source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = dict(payload or {})
    kind = str(source.get("kind") or source.get("source_kind") or "").strip()
    source_type = str(source.get("source_type") or _source_type_from_kind(kind) or "filesystem").strip()
    display_name = str(source.get("display_name") or source.get("name") or source.get("title") or "").strip()
    metadata = dict(source.get("metadata") or {})
    if display_name:
        metadata.setdefault("display_name", display_name)
        metadata.setdefault("title", display_name)
    uri = str(source.get("uri") or source.get("path") or source.get("url") or "").strip()
    if source_type == "manual_note":
        content = str(source.get("content") or metadata.get("content") or uri).strip()
        metadata["content"] = content
        uri = content
    result = {
        "source_type": source_type,
        "mount_mode": str(source.get("mount_mode") or source.get("mode") or "index_only").strip(),
        "uri": uri,
        "metadata": metadata,
    }
    if display_name:
        result["display_name"] = display_name
    source_id = str(source.get("source_id") or "").strip()
    if source_id:
        result["source_id"] = source_id
    if source.get("ingestion_plan") is not None:
        result["ingestion_plan"] = source.get("ingestion_plan")
    return result


def _source_type_from_kind(kind: str) -> str | None:
    if kind in {"folder", "file", "filesystem"}:
        return "filesystem"
    if kind in {"url", "web", "web_snapshot"}:
        return "web_snapshot"
    if kind in {"note", "manual_note"}:
        return "manual_note"
    return None
