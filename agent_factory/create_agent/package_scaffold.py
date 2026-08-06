from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.create_agent.contract_catalog import base_contract_paths, default_contract_payload
from agent_factory.runtime_contracts.schema import AgentPackageManifest


PACKAGE_ASSET_DIRECTORIES = (
    "tools",
    "knowledge",
    "artifacts",
)

SUPPORTED_SCAFFOLD_PATTERNS = {"react_agent", "plan_and_execute"}


def materialize_empty_agent_package(
    root: str | Path,
    *,
    factory_run_id: str,
    user_input: str = "",
    pattern_id: str,
) -> None:
    package_root = Path(root).expanduser().resolve()
    package_root.mkdir(parents=True, exist_ok=True)
    for relative in PACKAGE_ASSET_DIRECTORIES:
        (package_root / relative).mkdir(parents=True, exist_ok=True)
    manifest_path = package_root / "agent_package.json"
    if manifest_path.exists():
        return
    selected_pattern_id = _selected_pattern_id(pattern_id)
    manifest_agent = _agent_identity(user_input=user_input)
    assembly_agent = _assembly_agent_identity(user_input=user_input)
    contracts = base_contract_paths()
    _write_json(
        manifest_path,
        AgentPackageManifest(
            factory_run_id=factory_run_id,
            agent=manifest_agent,
            runtime={"pattern_id": selected_pattern_id},
            assembly_spec_path="assembly_spec.json",
            contracts=contracts,
            tools=[],
        ).model_dump(mode="json", exclude_none=True),
    )
    _write_json(
        package_root / "assembly_spec.json",
        AgentAssemblySpec(
            agent=assembly_agent,
            runtime={"pattern_id": selected_pattern_id},
        ).model_dump(mode="json", exclude_none=True),
    )
    for contract_key in sorted(contracts):
        _write_json(package_root / contracts[contract_key], default_contract_payload(contract_key))


def _agent_identity(*, user_input: str) -> dict[str, Any]:
    return _assembly_agent_identity(user_input=user_input)


def _assembly_agent_identity(*, user_input: str) -> dict[str, Any]:
    summary = " ".join(str(user_input or "").split())
    description = summary[:240] if summary else "Generated RuntimeKernel AgentPackage."
    return {
        "id": "generated_agent",
        "name": "Generated Agent",
        "description": description,
        "version": "0.1.0",
    }


def _selected_pattern_id(pattern_id: str) -> str:
    value = str(pattern_id or "").strip()
    if value not in SUPPORTED_SCAFFOLD_PATTERNS:
        raise ValueError(f"unsupported scaffold pattern_id: {value or '<empty>'}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
