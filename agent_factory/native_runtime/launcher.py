"""Local process launcher for cross-platform agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any

from agent_factory.agent_runtime_bridge.paths import (
    BRIDGE_ARTIFACTS_ROOT_ENV,
    BRIDGE_EXTENSION_ROOT_ENV,
    BRIDGE_PACKAGE_ROOT_ENV,
    BRIDGE_RUNTIME_ROOT_ENV,
    BRIDGE_RUNTIME_INSTANCE_ID_ENV,
    BRIDGE_WORKDIR_ROOT_ENV,
)
from agent_factory.model_pool import (
    MODEL_POOL_STORE_PATH_ENV,
    MODEL_POOL_STORE_READ_ONLY_ENV,
    ModelPoolStore,
    resolve_model_pool_store_path,
)
from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_attachments import workspace_attachment_root
from agent_factory.environment_system import (
    EnvironmentResolver,
    dependency_pool_path,
)
from agent_factory.environment_system.runtime import (
    DEPENDENCY_POOL_ROOT_ENV,
    ENVIRONMENT_LOCK_PATH_ENV,
)
from agent_factory.resource_system import ResourceStore
from agent_factory.resource_system.store import (
    RESOURCE_MASTER_KEY_ENV,
    RESOURCE_STORE_PATH_ENV,
    RESOURCE_STORE_READ_ONLY_ENV,
)
from agent_factory.runtime_contracts import LoadedAgentPackage


@dataclass(frozen=True, slots=True)
class NativeAgentRuntimePlan:
    """Local process launch plan for an AgentPackage runtime."""

    command: list[str]
    environment: dict[str, str]
    extension_root: Path
    service_env: dict[str, str]
    preflight: dict[str, Any]
    isolation: str = "native"

    def command_for_python_module(self, module: str) -> list[str]:
        """Replace the stdio_server module with another Python module."""
        if self.command[-2:] != ["-m", "agent_factory.agent_runtime_bridge.stdio_server"]:
            raise ValueError("runtime command does not end with a Python module entrypoint")
        return [*self.command[:-2], "-m", module]


class AgentRuntimeLaunchError(RuntimeError):
    """Raised when native agent runtime launch fails."""

    def __init__(
        self, *, where: str, why: str, message: str, suggested_action: str | None = None
    ) -> None:
        super().__init__(message)
        self.payload = {
            "where": where,
            "why": why,
            "message": message,
            "suggested_action": suggested_action,
        }


class NativeAgentRuntimeLauncher:
    """Launches an AgentPackage runtime as a local subprocess."""

    def prepare(
        self,
        *,
        package: LoadedAgentPackage,
        runtime_root: Path,
        artifacts_root: Path,
        workdir_root: Path,
        runtime_instance_id: str,
        extension_root: Path | None = None,
        mcp_gateway_url: str | None = None,
        skillhub_gateway_url: str | None = None,
    ) -> NativeAgentRuntimePlan:
        """Prepare native subprocess launch plan."""
        runtime_instance_id = str(runtime_instance_id or "").strip()
        if not runtime_instance_id:
            raise AgentRuntimeLaunchError(
                where="native.runtime_instance",
                why="runtime_instance_id_missing",
                message="Native Agent runtime requires a stable runtime instance identifier.",
            )

        # Read environment lock
        environment_lock = EnvironmentResolver().read_lock(package.package_root)

        # Prepare runtime extension root
        extension_root = extension_root or runtime_root / "extensions"
        extension_root = self._prepare_runtime_extension_root(
            source_extension_root=extension_root,
            runtime_root=runtime_root,
        )

        # Validate workspace structure
        _assert_package_runtime_workspace(
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            extension_root=extension_root,
        )

        # Create input files directory
        input_files_root = workspace_attachment_root(workdir_root)
        input_files_root.mkdir(parents=True, exist_ok=True)

        # Prepare control plane snapshots (model pool, resource store)
        model_pool_path = resolve_model_pool_store_path()
        ModelPoolStore(model_pool_path)
        resource_store = ResourceStore()
        control_plane_root = runtime_root / "control_plane"
        control_plane_root.mkdir(parents=True, exist_ok=True)
        model_pool_snapshot = control_plane_root / "model_pool.sqlite"
        resource_store_snapshot = control_plane_root / "resources.sqlite"
        _copy_sqlite_snapshot(model_pool_path, model_pool_snapshot)
        _copy_sqlite_snapshot(resource_store.path, resource_store_snapshot)

        # Prepare the cross-process background-task control plane.
        background_task_root = factory_artifact_path("background_tasks")
        background_task_root.mkdir(parents=True, exist_ok=True)

        # Prepare dependency pool
        dependency_pool = dependency_pool_path()
        dependency_pool.mkdir(parents=True, exist_ok=True)

        # Build environment variables
        env = self._build_native_environment(
            package=package,
            environment_lock=environment_lock,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            extension_root=extension_root,
            runtime_instance_id=runtime_instance_id,
            model_pool_snapshot=model_pool_snapshot,
            resource_store_snapshot=resource_store_snapshot,
            background_task_root=background_task_root,
            dependency_pool=dependency_pool,
            mcp_gateway_url=mcp_gateway_url,
            skillhub_gateway_url=skillhub_gateway_url,
        )

        service_env = {}  # TODO: Extract from sandbox when implementing contract mounts

        # Build command: current Python interpreter + stdio_server module
        command = [
            sys.executable,
            "-m",
            "agent_factory.agent_runtime_bridge.stdio_server",
        ]

        return NativeAgentRuntimePlan(
            command=command,
            environment=env,
            extension_root=extension_root,
            service_env=service_env,
            preflight={
                "status": "ok",
                "runtime_type": "native",
                "python_executable": sys.executable,
                "environment_lock": environment_lock,
                "extension_root": str(extension_root),
                "dependency_pool": str(dependency_pool),
                "service_env_keys": sorted(service_env),
                "mcp_gateway_url": mcp_gateway_url,
                "skillhub_gateway_url": skillhub_gateway_url,
                "isolation": "native",
                "runtime_instance_id": runtime_instance_id,
            },
            isolation="native",
        )

    def build_command(
        self,
        *,
        package: LoadedAgentPackage,
        runtime_root: Path,
        artifacts_root: Path,
        workdir_root: Path,
        runtime_instance_id: str,
        extension_root: Path | None = None,
        mcp_gateway_url: str | None = None,
        skillhub_gateway_url: str | None = None,
    ) -> list[str]:
        """Build command for launching native subprocess (legacy interface)."""
        return self.prepare(
            package=package,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            runtime_instance_id=runtime_instance_id,
            extension_root=extension_root,
            mcp_gateway_url=mcp_gateway_url,
            skillhub_gateway_url=skillhub_gateway_url,
        ).command

    def _build_native_environment(
        self,
        *,
        package: LoadedAgentPackage,
        environment_lock: dict[str, Any],
        runtime_root: Path,
        artifacts_root: Path,
        workdir_root: Path,
        extension_root: Path,
        runtime_instance_id: str,
        model_pool_snapshot: Path,
        resource_store_snapshot: Path,
        background_task_root: Path,
        dependency_pool: Path,
        mcp_gateway_url: str | None,
        skillhub_gateway_url: str | None,
    ) -> dict[str, str]:
        """Build environment variables for native subprocess."""
        env = dict(os.environ)

        # Bridge path configuration (host absolute paths)
        env[BRIDGE_PACKAGE_ROOT_ENV] = str(package.package_root.resolve())
        env[BRIDGE_ARTIFACTS_ROOT_ENV] = str(artifacts_root.resolve())
        env[BRIDGE_RUNTIME_ROOT_ENV] = str(runtime_root.resolve())
        env[BRIDGE_WORKDIR_ROOT_ENV] = str(workdir_root.resolve())
        env[BRIDGE_EXTENSION_ROOT_ENV] = str(extension_root.resolve())
        env[BRIDGE_RUNTIME_INSTANCE_ID_ENV] = runtime_instance_id

        # Dependency pool configuration
        env[DEPENDENCY_POOL_ROOT_ENV] = str(dependency_pool.resolve())
        env[ENVIRONMENT_LOCK_PATH_ENV] = str(
            (package.package_root / "environment.lock.json").resolve()
        )

        # Build PYTHONPATH from dependency pool
        python_paths = self._build_pythonpath_from_pool(environment_lock, dependency_pool)
        if python_paths:
            existing_pythonpath = env.get("PYTHONPATH", "")
            combined = os.pathsep.join(python_paths)
            env["PYTHONPATH"] = (
                f"{combined}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else combined
            )

        # Build NODE_PATH from dependency pool
        node_path = self._build_node_path_from_pool(environment_lock, dependency_pool)
        if node_path:
            existing_node_path = env.get("NODE_PATH", "")
            env["NODE_PATH"] = (
                f"{node_path}{os.pathsep}{existing_node_path}" if existing_node_path else node_path
            )

        # Model pool and resource store
        env[MODEL_POOL_STORE_PATH_ENV] = str(model_pool_snapshot.resolve())
        env[MODEL_POOL_STORE_READ_ONLY_ENV] = "1"
        env[RESOURCE_STORE_PATH_ENV] = str(resource_store_snapshot.resolve())
        env[RESOURCE_STORE_READ_ONLY_ENV] = "1"
        if ResourceStore().key_available:
            env[RESOURCE_MASTER_KEY_ENV] = os.environ[RESOURCE_MASTER_KEY_ENV]

        # Background-task control plane
        env["AGENTFACTORY_BACKGROUND_TASK_ROOT"] = str(background_task_root.resolve())

        # Gateway URLs
        if mcp_gateway_url:
            env["AGENTFACTORY_MCP_GATEWAY_URL"] = mcp_gateway_url
        if skillhub_gateway_url:
            env["AGENTFACTORY_SKILLHUB_GATEWAY_URL"] = skillhub_gateway_url

        return env

    def _build_pythonpath_from_pool(
        self, environment_lock: dict[str, Any], dependency_pool: Path
    ) -> list[str]:
        """Build PYTHONPATH from dependency pool entries."""
        pool = environment_lock.get("pool")
        if not isinstance(pool, dict):
            return []

        python_entries = pool.get("python_entries")
        if not isinstance(python_entries, list):
            return []

        paths: list[str] = []
        for entry in python_entries:
            if not isinstance(entry, dict):
                continue
            relative_path = entry.get("path")
            if not relative_path:
                continue
            site_packages = dependency_pool / relative_path / "site-packages"
            if site_packages.exists():
                paths.append(str(site_packages.resolve()))

        return paths

    def _build_node_path_from_pool(
        self, environment_lock: dict[str, Any], dependency_pool: Path
    ) -> str | None:
        """Build NODE_PATH from dependency pool npm profile."""
        pool = environment_lock.get("pool")
        if not isinstance(pool, dict):
            return None

        npm_profile = pool.get("npm_profile")
        if not isinstance(npm_profile, dict):
            return None

        relative_path = npm_profile.get("path")
        if not relative_path:
            return None

        node_modules = dependency_pool / relative_path / "node_modules"
        if node_modules.exists():
            return str(node_modules.resolve())

        return None

    def _prepare_runtime_extension_root(
        self, *, source_extension_root: Path, runtime_root: Path
    ) -> Path:
        """Prepare extension root (copy from source if needed)."""
        runtime_extension_root = runtime_root / "extensions"
        source = source_extension_root.expanduser().resolve()
        target = runtime_extension_root.resolve()

        if source == target:
            target.mkdir(parents=True, exist_ok=True)
            return target

        if source.exists():
            import shutil

            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            target.mkdir(parents=True, exist_ok=True)

        return target


def _assert_package_runtime_workspace(
    *,
    runtime_root: Path,
    artifacts_root: Path,
    workdir_root: Path,
    extension_root: Path,
) -> None:
    """Validate package-owned paths and the explicitly selected workdir."""
    root = runtime_root.resolve()
    for field_name, path in (
        ("artifacts_root", artifacts_root),
        ("extension_root", extension_root),
    ):
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise AgentRuntimeLaunchError(
                where="native.runtime_workspace",
                why="writable_path_outside_package_runtime",
                message=(
                    f"{field_name} must resolve inside the package runtime workspace: "
                    f"root={root}, path={resolved}"
                ),
            ) from exc
    resolved_workdir = workdir_root.expanduser().resolve()
    if resolved_workdir == resolved_workdir.parent:
        raise AgentRuntimeLaunchError(
            where="native.runtime_workspace",
            why="unsafe_workspace_root",
            message="workdir_root must not be a filesystem root",
        )
    resolved_workdir.mkdir(parents=True, exist_ok=True)


def _copy_sqlite_snapshot(source: Path, target: Path) -> None:
    """Create a simple file copy of SQLite database for runtime snapshot."""
    from agent_factory.sqlite_runtime import connect_sqlite
    from contextlib import closing

    source_path = source.expanduser().resolve()
    target_path = target.expanduser().resolve()

    if not source_path.is_file():
        raise AgentRuntimeLaunchError(
            where="native.control_plane_snapshot",
            why="source_database_missing",
            message=f"Runtime control-plane database is not initialized: {source_path}",
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_suffix(target_path.suffix + ".tmp")
    temporary_path.unlink(missing_ok=True)

    try:
        with closing(
            connect_sqlite(
                f"{source_path.as_uri()}?mode=ro",
                uri=True,
                query_only=True,
            )
        ) as source_conn:
            with closing(connect_sqlite(temporary_path)) as target_conn:
                source_conn.backup(target_conn)
                target_conn.commit()
        temporary_path.replace(target_path)
    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        raise AgentRuntimeLaunchError(
            where="native.control_plane_snapshot",
            why="snapshot_failed",
            message=f"Failed to snapshot runtime control-plane database {source_path}: {exc}",
        ) from exc
