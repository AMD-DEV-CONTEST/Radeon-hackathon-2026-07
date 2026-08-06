from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


BRIDGE_PACKAGE_ROOT_ENV = "AGENTFACTORY_BRIDGE_PACKAGE_ROOT"
BRIDGE_ARTIFACTS_ROOT_ENV = "AGENTFACTORY_BRIDGE_ARTIFACTS_ROOT"
BRIDGE_RUNTIME_ROOT_ENV = "AGENTFACTORY_BRIDGE_RUNTIME_ROOT"
BRIDGE_WORKDIR_ROOT_ENV = "AGENTFACTORY_BRIDGE_WORKDIR_ROOT"
BRIDGE_EXTENSION_ROOT_ENV = "AGENTFACTORY_BRIDGE_EXTENSION_ROOT"
BRIDGE_RUNTIME_INSTANCE_ID_ENV = "AGENTFACTORY_BRIDGE_RUNTIME_INSTANCE_ID"


@dataclass(frozen=True, slots=True)
class RuntimeBridgePaths:
    package_root: Path
    artifacts_root: Path
    runtime_root: Path
    workdir_root: Path
    extension_root: Path
    runtime_instance_id: str | None


def runtime_bridge_paths() -> RuntimeBridgePaths:
    runtime_root = Path(os.getenv(BRIDGE_RUNTIME_ROOT_ENV, "/runtime"))
    return RuntimeBridgePaths(
        package_root=Path(os.getenv(BRIDGE_PACKAGE_ROOT_ENV, "/package")),
        artifacts_root=Path(os.getenv(BRIDGE_ARTIFACTS_ROOT_ENV, "/artifacts")),
        runtime_root=runtime_root,
        workdir_root=Path(os.getenv(BRIDGE_WORKDIR_ROOT_ENV, "/workdir")),
        extension_root=Path(
            os.getenv(BRIDGE_EXTENSION_ROOT_ENV, str(runtime_root / "extensions"))
        ),
        runtime_instance_id=(os.getenv(BRIDGE_RUNTIME_INSTANCE_ID_ENV, "").strip() or None),
    )
