from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from agent_factory.tooling.extension_registry import (
    load_agent_extension_bindings,
    load_registered_mcp_servers,
    save_agent_extension_bindings,
)
from agent_factory.tooling.factory_extensions import FactoryExtensionManager
from agent_factory.tooling.providers.mcp import MCPServerConfig


PACKAGE_EXTENSION_ROOT = "extensions"


@dataclass(frozen=True, slots=True)
class MCPInheritanceResult:
    changed_files: list[str] = field(default_factory=list)
    inherited_tool_ids: list[str] = field(default_factory=list)
    inherited_server_ids: list[str] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changed_files)

    def model_dump(self) -> dict[str, Any]:
        return {
            "changed_files": self.changed_files,
            "inherited_tool_ids": self.inherited_tool_ids,
            "inherited_server_ids": self.inherited_server_ids,
            "diagnostics": _json_safe(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class FactoryMCPInventory:
    tool_to_server: dict[str, str]
    servers: dict[str, MCPServerConfig]
    diagnostics: list[dict[str, Any]]

    @property
    def tool_ids(self) -> set[str]:
        return set(self.tool_to_server)


def materialize_referenced_factory_mcp(package_root: str | Path) -> MCPInheritanceResult:
    root = Path(package_root).expanduser().resolve()
    manifest = _read_json(root / "agent_package.json")
    referenced_tool_ids = _referenced_tool_ids(root / str(manifest.get("assembly_spec_path") or "assembly_spec.json"))
    if not referenced_tool_ids:
        return MCPInheritanceResult()
    inventory = discover_factory_mcp_inventory()
    matched_tool_ids = sorted(tool_id for tool_id in referenced_tool_ids if tool_id in inventory.tool_to_server)
    if not matched_tool_ids:
        return MCPInheritanceResult(diagnostics=inventory.diagnostics)
    server_ids = sorted({inventory.tool_to_server[tool_id] for tool_id in matched_tool_ids})
    servers = [inventory.servers[server_id] for server_id in server_ids if server_id in inventory.servers]
    if not servers:
        return MCPInheritanceResult(
            inherited_tool_ids=matched_tool_ids,
            diagnostics=[
                *inventory.diagnostics,
                {
                    "level": "warning",
                    "message": "referenced MCP tools matched no inheritable server config",
                    "tool_ids": matched_tool_ids,
                },
            ],
        )
    changed_files: set[str] = set()
    tools_contract_path = root / str((manifest.get("contracts") or {}).get("tools") or "contracts/tools.json")
    if _ensure_package_extension_root(tools_contract_path):
        changed_files.add(_relative(root, tools_contract_path))
    extension_root = root / PACKAGE_EXTENSION_ROOT
    extension_root.mkdir(parents=True, exist_ok=True)
    bindings_path = extension_root / "extension_bindings.json"
    current_bindings = load_agent_extension_bindings([extension_root])
    next_bindings = current_bindings.model_copy(
        update={
            "mcp_server_ids": sorted(
                {*current_bindings.mcp_server_ids, *server_ids}
            )
        }
    )
    if next_bindings != current_bindings:
        save_agent_extension_bindings(extension_root, next_bindings)
        changed_files.add(_relative(root, bindings_path))
    return MCPInheritanceResult(
        changed_files=sorted(changed_files),
        inherited_tool_ids=matched_tool_ids,
        inherited_server_ids=server_ids,
        diagnostics=inventory.diagnostics,
    )


def discover_factory_mcp_inventory() -> FactoryMCPInventory:
    manager = FactoryExtensionManager()
    result, report = manager.discover_registry()
    tool_to_server: dict[str, str] = {}
    diagnostics = [diagnostic.model_dump(mode="json") if hasattr(diagnostic, "model_dump") else dict(diagnostic) for diagnostic in result.diagnostics]
    for spec in result.tool_specs:
        server_id = _server_id_from_entrypoint(str(spec.entrypoint))
        if server_id:
            tool_to_server[spec.id] = server_id
    servers = {
        server.server_id: server
        for server in load_registered_mcp_servers().servers
        if server.enabled
    }
    diagnostics.append(report.model_dump(mode="json"))
    return FactoryMCPInventory(tool_to_server=tool_to_server, servers=servers, diagnostics=diagnostics)


def factory_mcp_tool_ids() -> set[str]:
    return discover_factory_mcp_inventory().tool_ids


def materialized_package_mcp_tool_ids(package_root: str | Path) -> set[str]:
    root = Path(package_root).expanduser().resolve()
    manifest = _read_json(root / "agent_package.json")
    tools_contract_path = root / str((manifest.get("contracts") or {}).get("tools") or "contracts/tools.json")
    tools_contract = _read_json(tools_contract_path)
    config = tools_contract.get("config") if isinstance(tools_contract.get("config"), dict) else {}
    extension_root = str(config.get("instance_extension_root") or PACKAGE_EXTENSION_ROOT).strip() or PACKAGE_EXTENSION_ROOT
    package_bindings = load_agent_extension_bindings([root / extension_root])
    package_server_ids = set(package_bindings.mcp_server_ids)
    inventory = discover_factory_mcp_inventory()
    return {
        tool_id
        for tool_id, server_id in inventory.tool_to_server.items()
        if server_id in package_server_ids
    }


def _referenced_tool_ids(assembly_path: Path) -> set[str]:
    payload = _read_json(assembly_path)
    ids: set[str] = set()
    bindings = ((payload.get("bindings") or {}).get("node_bindings") or [])
    if not isinstance(bindings, list):
        return ids
    for binding in bindings:
        if not isinstance(binding, dict) or binding.get("binding_type") != "tool_access":
            continue
        allowed = ((binding.get("payload") or {}).get("allowed_tool_ids") or [])
        if isinstance(allowed, list):
            ids.update(str(tool_id).strip() for tool_id in allowed if str(tool_id).strip())
    return ids


def _ensure_package_extension_root(tools_contract_path: Path) -> bool:
    payload = _read_json(tools_contract_path)
    config = payload.setdefault("config", {})
    if not isinstance(config, dict):
        config = {}
        payload["config"] = config
    before = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    config["instance_extensions_enabled"] = True
    config["instance_extension_root"] = PACKAGE_EXTENSION_ROOT
    after = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if before == after:
        return False
    _write_json(tools_contract_path, payload)
    return True


def _server_id_from_entrypoint(entrypoint: str) -> str:
    if not entrypoint.startswith("mcp:"):
        return ""
    target = entrypoint.removeprefix("mcp:")
    server_id, _, tool_name = target.partition("/")
    return server_id if server_id and tool_name else ""


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return str(value)
    return str(value)
