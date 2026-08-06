from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_contracts import LoadedAgentPackage
from agent_factory.tooling.factory_extensions import default_system_agent_extension_root


MANUFACTURING_PROBE_RUNTIME_NAMESPACE = ".manufacturing_probes"
SESSION_WORKDIRS_DIR = "sessions"


@dataclass(frozen=True, slots=True)
class PackageRuntimeWorkspace:
    """Stable writable workspace owned by exactly one AgentPackage.

    A package owns one persistent runtime process root. Each chat session owns
    a stable child workdir so runtime reuse does not imply shared file state.
    """

    root: Path
    workdir: Path
    artifacts: Path
    extensions: Path

    def ensure(self) -> "PackageRuntimeWorkspace":
        for path in (self.root, self.workdir, self.artifacts, self.extensions):
            path.mkdir(parents=True, exist_ok=True)
        return self

    def session_workdir(self, session_id: str) -> Path:
        identifier = str(session_id or "").strip()
        if not identifier:
            raise ValueError("session_id is required for a session workdir")
        return root_relative_path(
            self.workdir / SESSION_WORKDIRS_DIR,
            Path(identifier),
            field_path="agent package session workdir",
        )


def package_runtime_workspace(package_id: str) -> PackageRuntimeWorkspace:
    root = factory_artifact_path("agent_runtime", package_id)
    return PackageRuntimeWorkspace(
        root=root,
        workdir=root / "workdirs",
        artifacts=root / "artifacts",
        extensions=root / "extensions",
    )


def manufacturing_probe_runtime_workspace(workspace_id: str) -> PackageRuntimeWorkspace:
    """Allocate one probe workspace inside the shared writable runtime mount."""

    identifier = str(workspace_id or "").strip()
    if not identifier or identifier in {".", ".."} or "/" in identifier or "\\" in identifier:
        raise ValueError(f"invalid manufacturing workspace id: {workspace_id!r}")
    runtime_parent = factory_artifact_path("agent_runtime", MANUFACTURING_PROBE_RUNTIME_NAMESPACE)
    root = root_relative_path(
        runtime_parent,
        Path(identifier),
        field_path="manufacturing probe runtime workspace",
    )
    return PackageRuntimeWorkspace(
        root=root,
        workdir=root / "workdir",
        artifacts=root / "artifacts",
        extensions=root / "extensions",
    )


def host_runtime_root(package_id: str) -> Path:
    return package_runtime_workspace(package_id).root


def host_package_workdir(package_id: str) -> Path:
    return package_runtime_workspace(package_id).workdir


def host_session_workdir(package_id: str, session_id: str) -> Path:
    return package_runtime_workspace(package_id).session_workdir(session_id)


def host_session_root(*, package_id: str, package: LoadedAgentPackage, configured: str) -> Path:
    value = configured.strip()
    runtime_root = host_runtime_root(package_id)
    if value == "/runtime":
        return runtime_root.resolve()
    if value.startswith("/runtime/"):
        return root_relative_path(
            runtime_root,
            Path(value.removeprefix("/runtime/")),
            field_path="session.config.session_root",
        )
    if value == ".agent_runtime":
        return runtime_root.resolve()
    if value.startswith(".agent_runtime/"):
        return root_relative_path(
            runtime_root,
            Path(value.removeprefix(".agent_runtime/")),
            field_path="session.config.session_root",
        )
    path = Path(value).expanduser()
    if path.is_absolute():
        raise ValueError(
            "session.config.session_root must be package-relative or use /runtime/... "
            f"when a runtime workspace is mounted; got {value!r}"
        )
    return root_relative_path(package.package_root, path, field_path="session.config.session_root")


def extension_root_for_package(package_id: str, package: LoadedAgentPackage) -> Path:
    if package_id == "factory_chat" and is_system_package(package):
        return default_system_agent_extension_root("factory_chat")
    if is_system_package(package):
        return package.package_root.parent / "extensions"
    return package_runtime_workspace(package_id).extensions


def runtime_contract_path(runtime_root: Path, configured: str) -> Path:
    value = str(configured or "").strip()
    if not value:
        raise ValueError("runtime contract path must not be empty")
    if value == "/runtime":
        return runtime_root.resolve()
    if value.startswith("/runtime/"):
        return root_relative_path(
            runtime_root,
            Path(value.removeprefix("/runtime/")),
            field_path="runtime contract path",
        )
    if value == ".agent_runtime":
        return runtime_root.resolve()
    if value.startswith(".agent_runtime/"):
        return root_relative_path(
            runtime_root,
            Path(value.removeprefix(".agent_runtime/")),
            field_path="runtime contract path",
        )
    path = Path(value).expanduser()
    if path.is_absolute():
        raise ValueError(f"runtime contract path must resolve inside runtime workspace; got {value!r}")
    return root_relative_path(runtime_root, path, field_path="runtime contract path")


def root_relative_path(root_path: Path, path: Path, *, field_path: str) -> Path:
    root = root_path.resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field_path} must resolve inside its runtime workspace; got {str(path)!r}") from exc
    return target


def is_system_package(package: LoadedAgentPackage) -> bool:
    return bool(package.manifest.runtime.get("system_package"))


def is_host_system_package(package: LoadedAgentPackage) -> bool:
    if not is_system_package(package):
        return False
    backend = str(package.manifest.runtime.get("execution_backend") or "host").strip().lower()
    return backend == "host"
