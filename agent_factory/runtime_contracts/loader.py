from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_factory.runtime_contracts.schema import AgentPackageManifest


@dataclass(frozen=True, slots=True)
class LoadedAgentPackage:
    package_root: Path
    manifest_path: Path
    manifest: AgentPackageManifest
    assembly_spec: Any
    contracts: dict[str, dict[str, Any]]


class AgentPackageLoader:
    def load_path(self, path: str | Path) -> LoadedAgentPackage:
        manifest_path = Path(path)
        manifest = AgentPackageManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        package_root = manifest_path.parent

        assembly_spec = _agent_assembly_spec_model().model_validate_json(
            _read_package_file(package_root, manifest.assembly_spec_path)
        )
        contracts = {
            key: _json_object(_read_package_file(package_root, value), f"contracts.{key}")
            for key, value in manifest.contracts.items()
        }
        return LoadedAgentPackage(
            package_root=package_root,
            manifest_path=manifest_path,
            manifest=manifest,
            assembly_spec=assembly_spec,
            contracts=contracts,
        )


def _agent_assembly_spec_model():
    return importlib.import_module("agent_factory.assembly.schema").AgentAssemblySpec


def _read_package_file(package_root: Path, relative_path: str) -> str:
    return _package_file_path(package_root, relative_path).read_text(encoding="utf-8")


def _package_file_path(package_root: Path, relative_path: str) -> Path:
    target = (package_root / relative_path).resolve()
    root = package_root.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"package path escapes package root: {relative_path}") from exc
    if not target.is_file():
        raise FileNotFoundError(f"package file not found: {relative_path}")
    return target


def _json_object(content: str, label: str) -> dict[str, Any]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value
