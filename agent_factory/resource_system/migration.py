from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.resource_system.store import ResourceStore, ResourceStoreError
from agent_factory.runtime_contracts.schema import ResourceDescriptor, ResourcesContract


def migrate_package_resources(package_root: Path, *, store: ResourceStore) -> dict[str, Any]:
    manifest_path = package_root / "agent_package.json"
    legacy_path = package_root / "resources.json"
    if not manifest_path.is_file():
        return {"status": "not_package"}
    manifest = _read_object(manifest_path)
    legacy_declared = "resources_path" in manifest
    if not legacy_declared and not legacy_path.exists():
        return {"status": "complete", "migrated": False}
    contract_path = package_root / "contracts" / "resources.json"
    if not contract_path.is_file():
        return {"status": "pending", "reason": "resource contract is missing"}
    contract_payload = _read_object(contract_path)
    config = contract_payload.get("config")
    if isinstance(config, dict):
        config.pop("resources_path", None)
    contract = ResourcesContract.model_validate(contract_payload)
    _write_object(contract_path, contract.model_dump(mode="json"))
    descriptors = {item.resource_id: item for item in contract.config.resource_descriptors}
    values = _read_object(legacy_path) if legacy_path.is_file() else {}
    unknown = sorted(set(values) - set(descriptors))
    if unknown:
        return {"status": "pending", "reason": "legacy values are not declared", "resource_ids": unknown}
    if values and not store.key_available:
        return {"status": "pending", "reason": "resource master key is unavailable"}
    try:
        for resource_id, value in values.items():
            store.put(package_root.name, descriptors[resource_id], value)
    except ResourceStoreError as exc:
        return {"status": "pending", "reason": str(exc)}
    manifest.pop("resources_path", None)
    _write_object(manifest_path, manifest)
    legacy_path.unlink(missing_ok=True)
    return {"status": "complete", "migrated": legacy_declared or bool(values)}


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_object(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
