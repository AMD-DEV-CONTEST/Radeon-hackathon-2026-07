from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from agent_factory.create_agent.package_paths import is_transient_package_path
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.package_tool_spec import package_tool_directory_path

ValidationScope = str
PACKAGE_TOOL_DIGEST_KIND = "package_tool_surface.v2"
PACKAGE_TOOL_SHARED_DEPENDENCY_PATHS = {"contracts/dependencies.json"}


def package_fingerprint(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    fingerprint: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if _ignore_path(relative):
            continue
        fingerprint[relative] = sha256(path.read_bytes()).hexdigest()
    return fingerprint


def package_digest(root: Path) -> str:
    fingerprint = package_fingerprint(root)
    return sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def package_tool_fingerprint(root: Path, tool_id: str, *, fingerprint: dict[str, str] | None = None) -> dict[str, str]:
    if not tool_id or "/" in tool_id or "\\" in tool_id or tool_id in {".", ".."}:
        return {}
    package_files = fingerprint if fingerprint is not None else package_fingerprint(root)
    prefix = f"{package_tool_directory_path(tool_id)}/"
    return {
        path: digest
        for path, digest in package_files.items()
        if path.startswith(prefix) or path in PACKAGE_TOOL_SHARED_DEPENDENCY_PATHS
    }


def package_tool_digest(root: Path, tool_id: str, *, fingerprint: dict[str, str] | None = None) -> str:
    payload = {
        "kind": PACKAGE_TOOL_DIGEST_KIND,
        "tool_id": tool_id,
        "fingerprint": package_tool_fingerprint(root, tool_id, fingerprint=fingerprint),
    }
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def changed_files(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    paths = set(previous) | set(current)
    return sorted(path for path in paths if previous.get(path) != current.get(path))


def tool_probe_digest(workspace: CreateAgentWorkspace) -> str:
    path = workspace.tool_probe_path
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "unreadable"
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def validation_scope_for_focus(validation_focus: str) -> ValidationScope:
    if validation_focus in {"full_static", "assembly_compile", "package_shape", "python_syntax", "runtime_contract_build"}:
        return validation_focus
    if validation_focus in {
        "runtime_contract_build_subset",
        "tools_contract_validate",
        "scheduler_seed_validate",
    }:
        return "runtime_contract_build"
    if validation_focus == "package_tool_syntax_and_binding":
        return "python_syntax"
    return "workspace_hygiene"


def _ignore_path(relative: str) -> bool:
    return is_transient_package_path(relative)
