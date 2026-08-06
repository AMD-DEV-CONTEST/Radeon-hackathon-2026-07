from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any
import zipfile

from agent_factory.create_agent.package_paths import (
    is_transient_package_path,
    normalize_package_relative,
)
from agent_factory.tooling.extension_registry import (
    AgentExtensionBindings,
    import_registered_skill_directory,
    load_agent_extension_bindings,
    load_registered_mcp_servers,
    load_registered_skills,
    remove_registered_extension,
    save_registered_mcp_servers,
    save_registered_skills,
    save_agent_extension_bindings,
    selected_registry_configs,
    upsert_registered_mcp_servers,
)
from agent_factory.tooling.providers import EnabledSkillsConfig, MCPServersConfig
from agent_factory.tooling.skills import parse_skill_directory


PACKAGE_ASSET_DIRS = frozenset(
    {
        "artifacts",
        "extensions",
        "formatters",
        "knowledge",
        "patterns",
        "policies",
        "prompts",
        "resources",
        "strategies",
        "tools",
    }
)
PACKAGE_REPORT_FILENAME = "package_report.json"
EXTENSION_DISTRIBUTION_FILENAME = "distribution_extensions.json"
EXTENSION_DISTRIBUTION_SKILLS_DIR = "distribution_skills"
DISTRIBUTION_LOCAL_PARTS = frozenset({".agent_runtime", ".factory", "checkpoints", "logs", "sessions"})
DISTRIBUTION_LOCAL_NAMES = frozenset({".env", "agent.sqlite", "runtime.sqlite"})
DISTRIBUTION_LOCAL_SUFFIXES = frozenset({".log", ".pyc", ".pyo"})


class PackageDistributionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PackageDistributionPolicy:
    publishable_files: frozenset[str]
    publishable_dirs: frozenset[str]

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> "PackageDistributionPolicy":
        files = {"agent_package.json", "environment.lock.json"}
        dirs: set[str] = set()
        _add_manifest_file(files, manifest.get("assembly_spec_path"))
        contracts = manifest.get("contracts")
        if isinstance(contracts, dict):
            for value in contracts.values():
                _add_manifest_file(files, value)
        for key in (
            "bindings",
            "patterns",
            "prompts",
            "tools",
            "policies",
            "strategies",
            "formatters",
        ):
            value = manifest.get(key)
            items = value if isinstance(value, list) else value.values() if isinstance(value, dict) else ()
            for item in items:
                _add_manifest_file(files, item)
                _add_asset_dir_for_manifest_path(dirs, item)
        return cls(
            publishable_files=frozenset(files),
            publishable_dirs=frozenset(dirs | set(PACKAGE_ASSET_DIRS)),
        )

    def allows(self, relative_path: str) -> bool:
        normalized = normalize_package_relative(relative_path)
        if (
            normalized == PACKAGE_REPORT_FILENAME
            or is_transient_package_path(normalized)
            or _is_distribution_local_path(normalized)
        ):
            return False
        if normalized in self.publishable_files:
            return True
        return any(
            normalized == directory or normalized.startswith(f"{directory}/")
            for directory in self.publishable_dirs
        )


def copy_publishable_package(source: Path, target: Path) -> None:
    policy = PackageDistributionPolicy.from_manifest(read_manifest_payload(source))
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        if path.is_symlink():
            continue
        relative = path.relative_to(source).as_posix()
        if not policy.allows(relative):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def distribution_extension_preview(source: Path, package_id: str) -> dict[str, Any]:
    _require_package_id(source, package_id)
    mcp_servers, skills, _ = selected_registry_configs([source / "extensions"])
    return {
        "package_id": package_id,
        "mcp_servers": mcp_servers.model_dump(mode="json"),
        "skills": _distribution_skills(skills),
    }


def export_distribution_archive(
    source: Path,
    package_id: str,
    archive_path: Path,
    *,
    extension_overrides: dict[str, Any] | None = None,
) -> None:
    _require_package_id(source, package_id)
    overrides = _validate_extension_overrides(extension_overrides)
    with tempfile.TemporaryDirectory(prefix="agent-package-distribution-") as temp_dir:
        snapshot_root = Path(temp_dir) / source.name
        copy_publishable_package(source, snapshot_root)
        skill_paths = _materialize_distribution_extensions(
            source=source,
            snapshot=snapshot_root,
        )
        _apply_extension_overrides(snapshot_root, overrides, skill_paths=skill_paths)
        _sanitize_resource_defaults(snapshot_root)
        _validate_distribution_extensions(snapshot_root)
        validate_distribution_snapshot(snapshot_root)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in snapshot_root.rglob("*") if item.is_file()):
                relative = Path(source.name) / path.relative_to(snapshot_root)
                archive.write(path, relative.as_posix())


def import_distribution_extensions(root: Path) -> dict[str, list[str]]:
    path = root / "extensions" / EXTENSION_DISTRIBUTION_FILENAME
    if not path.is_file():
        return {"mcp_servers": [], "skills": [], "preserved": []}
    _validate_distribution_extensions(root)
    payload = _read_extension_config(path, default={})
    mcp_config = MCPServersConfig.model_validate(payload.get("mcp_servers") or {})
    skills_config = EnabledSkillsConfig.model_validate(payload.get("skills") or {})
    bindings = load_agent_extension_bindings([root / "extensions"])
    bound_mcp_ids = set(bindings.mcp_server_ids)
    bound_skill_ids = set(bindings.skill_ids)
    if any(server.server_id not in bound_mcp_ids for server in mcp_config.servers):
        raise PackageDistributionError(
            "distribution MCP snapshot contains servers not declared by extension bindings"
        )
    if any(skill.skill_id not in bound_skill_ids for skill in skills_config.skills):
        raise PackageDistributionError(
            "distribution Skill snapshot contains Skills not declared by extension bindings"
        )

    current_mcp = load_registered_mcp_servers()
    current_skills = load_registered_skills()
    current_mcp_ids = {server.server_id for server in current_mcp.servers}
    current_skill_ids = {skill.skill_id for skill in current_skills.skills}
    new_mcp = [
        server for server in mcp_config.servers if server.server_id not in current_mcp_ids
    ]
    new_skills = [
        skill for skill in skills_config.skills if skill.skill_id not in current_skill_ids
    ]
    imported_skill_ids: list[str] = []
    try:
        for skill in new_skills:
            source = _distribution_skill_source(root, skill)
            imported = import_registered_skill_directory(
                source,
                enabled=skill.enabled,
                required=skill.required,
                source_kind="distribution",
                expected_skill_id=skill.skill_id,
            )
            if imported.skill_id != skill.skill_id:
                raise PackageDistributionError(
                    f"distributed Skill identity mismatch: {skill.skill_id} != {imported.skill_id}"
                )
            imported_skill_ids.append(imported.skill_id)
        if new_mcp:
            upsert_registered_mcp_servers(new_mcp)
    except Exception:
        for skill_id in imported_skill_ids:
            remove_registered_extension("skill", skill_id)
        save_registered_mcp_servers(current_mcp)
        save_registered_skills(current_skills)
        raise
    return {
        "mcp_servers": [server.server_id for server in new_mcp],
        "skills": imported_skill_ids,
        "preserved": sorted(
            {
                *(
                    server.server_id
                    for server in mcp_config.servers
                    if server.server_id in current_mcp_ids
                ),
                *(
                    skill.skill_id
                    for skill in skills_config.skills
                    if skill.skill_id in current_skill_ids
                ),
            }
        ),
    }


def _require_package_id(source: Path, package_id: str) -> None:
    manifest = read_manifest_payload(source)
    manifest_agent = manifest.get("agent")
    manifest_package_id = (
        str(manifest_agent.get("id") or "").strip()
        if isinstance(manifest_agent, dict)
        else ""
    )
    if manifest_package_id != package_id:
        raise PackageDistributionError(
            f"package id {package_id!r} does not match manifest id {manifest_package_id!r}"
        )


def read_manifest_payload(root: Path) -> dict[str, Any]:
    path = root / "agent_package.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PackageDistributionError("agent_package.json must be readable before distribution") from exc
    if not isinstance(payload, dict):
        raise PackageDistributionError("agent_package.json must contain a JSON object")
    return payload


def validate_distribution_snapshot(root: Path) -> None:
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise PackageDistributionError(f"symbolic links are not distributable: {relative}")
        if (
            is_transient_package_path(relative)
            or _is_distribution_local_path(relative)
            or relative == PACKAGE_REPORT_FILENAME
        ):
            raise PackageDistributionError(f"runtime or local-only file is not distributable: {relative}")


def _sanitize_resource_defaults(snapshot: Path) -> None:
    manifest = read_manifest_payload(snapshot)
    contracts = manifest.get("contracts")
    if not isinstance(contracts, dict):
        return
    relative = contracts.get("resources")
    if not isinstance(relative, str):
        return
    path = snapshot / normalize_package_relative(relative)
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = payload.get("config") if isinstance(payload, dict) else None
    descriptors = config.get("resource_descriptors") if isinstance(config, dict) else None
    if not isinstance(descriptors, list):
        return
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            continue
        default_value = descriptor.get("default_value")
        for field_path in descriptor.get("secret_fields") or []:
            if isinstance(field_path, str):
                _remove_nested_value(default_value, field_path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_nested_value(value: Any, field_path: str) -> None:
    separator = "/" if field_path.startswith("/") else "."
    parts = [part for part in field_path.split(separator) if part]
    current = value
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(part)
    if parts and isinstance(current, dict):
        current.pop(parts[-1], None)


def _read_extension_config(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PackageDistributionError(f"extension configuration is not readable: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PackageDistributionError(f"extension configuration must be an object: {path.name}")
    return payload


def _validate_extension_overrides(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PackageDistributionError("extension overrides must be an object")
    unknown = sorted(set(value) - {"mcp_servers", "skills"})
    if unknown:
        raise PackageDistributionError("unsupported extension overrides: " + ", ".join(unknown))
    overrides: dict[str, Any] = {}
    if "mcp_servers" in value:
        overrides["mcp_servers"] = MCPServersConfig.model_validate(
            value["mcp_servers"]
        ).model_dump(mode="json")
    if "skills" in value:
        raw_skills = value["skills"]
        if not isinstance(raw_skills, list):
            raise PackageDistributionError("Skill content overrides must be an array")
        skill_files: dict[str, list[dict[str, Any]]] = {}
        for item in raw_skills:
            if not isinstance(item, dict):
                raise PackageDistributionError("Skill content overrides must contain objects")
            skill_id = str(item.get("skill_id") or "").strip()
            files = item.get("files")
            if not skill_id or not isinstance(files, list):
                raise PackageDistributionError("Skill override requires skill_id and files")
            if skill_id in skill_files:
                raise PackageDistributionError(f"duplicate Skill content override: {skill_id}")
            normalized_files: list[dict[str, Any]] = []
            seen_paths: set[str] = set()
            for file_item in files:
                if not isinstance(file_item, dict):
                    raise PackageDistributionError("Skill file overrides must contain objects")
                relative_path = _safe_skill_file_path(file_item.get("path"))
                if relative_path in seen_paths:
                    raise PackageDistributionError(
                        f"duplicate Skill file override: {skill_id}/{relative_path}"
                    )
                included = file_item.get("included") is not False
                content = file_item.get("content")
                if content is not None and not isinstance(content, str):
                    raise PackageDistributionError(
                        f"Skill text content must be a string: {skill_id}/{relative_path}"
                    )
                normalized_files.append(
                    {
                        "path": relative_path,
                        "included": included,
                        "content": content,
                    }
                )
                seen_paths.add(relative_path)
            skill_files[skill_id] = normalized_files
        overrides["skills"] = skill_files
    return overrides


def _apply_extension_overrides(
    root: Path,
    overrides: dict[str, Any],
    *,
    skill_paths: dict[str, Path],
) -> None:
    mcp_payload = overrides.get("mcp_servers")
    if mcp_payload is not None:
        path = root / "extensions" / EXTENSION_DISTRIBUTION_FILENAME
        payload = _read_extension_config(path, default={})
        current = MCPServersConfig.model_validate(payload.get("mcp_servers") or {})
        replacement = MCPServersConfig.model_validate(mcp_payload)
        current_ids = {server.server_id for server in current.servers}
        replacement_ids = {server.server_id for server in replacement.servers}
        if replacement_ids != current_ids:
            raise PackageDistributionError(
                "MCP upload review may edit configuration values but cannot add or remove "
                "registered server identities"
            )
        payload["mcp_servers"] = mcp_payload
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    skill_overrides = overrides.get("skills")
    if skill_overrides is None:
        return
    unknown = sorted(set(skill_overrides) - set(skill_paths))
    if unknown:
        raise PackageDistributionError(
            "Skill content override references unconfigured Skills: " + ", ".join(unknown)
        )
    for skill_id, file_overrides in skill_overrides.items():
        skill_root = root / "extensions" / skill_paths[skill_id]
        available = {
            path.relative_to(skill_root).as_posix(): path
            for path in skill_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        requested = {item["path"]: item for item in file_overrides}
        unknown_files = sorted(set(requested) - set(available))
        if unknown_files:
            raise PackageDistributionError(
                f"Skill {skill_id!r} override references unknown files: "
                + ", ".join(unknown_files)
            )
        entry = requested.get("SKILL.md")
        if entry is None or entry["included"] is not True:
            raise PackageDistributionError(f"Skill {skill_id!r} must include SKILL.md")
        for relative_path, item in requested.items():
            path = available[relative_path]
            if item["included"] is not True:
                path.unlink()
                continue
            content = item.get("content")
            if content is not None:
                try:
                    path.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise PackageDistributionError(
                        f"binary Skill resource cannot be edited as text: {skill_id}/{relative_path}"
                    ) from exc
                path.write_text(content, encoding="utf-8")


def _distribution_skills(config: EnabledSkillsConfig) -> list[dict[str, Any]]:
    return [
        {
            "skill_id": skill.skill_id,
            "source": skill.source,
            "enabled": skill.enabled,
            "required": skill.required,
            "path": (
                Path(EXTENSION_DISTRIBUTION_SKILLS_DIR) / skill.skill_id
            ).as_posix(),
            "files": _skill_file_inventory(Path(skill.path).expanduser().resolve()),
        }
        for skill in config.skills
    ]


def _materialize_distribution_extensions(
    *,
    source: Path,
    snapshot: Path,
) -> dict[str, Path]:
    extensions_root = snapshot / "extensions"
    existing_distribution_skills = extensions_root / EXTENSION_DISTRIBUTION_SKILLS_DIR
    if existing_distribution_skills.exists():
        shutil.rmtree(existing_distribution_skills)
    (extensions_root / EXTENSION_DISTRIBUTION_FILENAME).unlink(missing_ok=True)
    mcp_config, skills_config, bindings = selected_registry_configs(
        [source / "extensions"]
    )
    save_agent_extension_bindings(extensions_root, bindings)
    skill_paths: dict[str, Path] = {}
    portable_skills = []
    for skill in skills_config.skills:
        source_root = Path(skill.path).expanduser().resolve()
        if not (source_root / "SKILL.md").is_file():
            raise PackageDistributionError(
                f"Skill {skill.skill_id!r} is registered but SKILL.md is missing"
            )
        symlink = next((path for path in source_root.rglob("*") if path.is_symlink()), None)
        if symlink is not None:
            raise PackageDistributionError(
                f"Skill {skill.skill_id!r} contains a symbolic link and cannot be distributed"
            )
        relative = Path(EXTENSION_DISTRIBUTION_SKILLS_DIR) / skill.skill_id
        destination = extensions_root / relative
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(
            source_root,
            destination,
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
        )
        skill_paths[skill.skill_id] = relative
        portable_skills.append(
            skill.model_copy(update={"path": relative.as_posix(), "source": "distribution"})
        )
    path = extensions_root / EXTENSION_DISTRIBUTION_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "extension_distribution.v0",
                "mcp_servers": mcp_config.model_dump(mode="json"),
                "skills": EnabledSkillsConfig(skills=portable_skills).model_dump(
                    mode="json"
                ),
                "bindings": bindings.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return skill_paths


def _validate_distribution_extensions(root: Path) -> None:
    path = root / "extensions" / EXTENSION_DISTRIBUTION_FILENAME
    payload = _read_extension_config(path, default={})
    mcp_config = MCPServersConfig.model_validate(payload.get("mcp_servers") or {})
    skills_config = EnabledSkillsConfig.model_validate(payload.get("skills") or {})
    bindings = load_agent_extension_bindings([root / "extensions"])
    snapshot_bindings = AgentExtensionBindings.model_validate(
        payload.get("bindings") or {}
    )
    if snapshot_bindings != bindings:
        raise PackageDistributionError(
            "distribution extension bindings do not match the package bindings"
        )
    bound_mcp_ids = set(bindings.mcp_server_ids)
    bound_skill_ids = set(bindings.skill_ids)
    if any(server.server_id not in bound_mcp_ids for server in mcp_config.servers):
        raise PackageDistributionError(
            "distribution MCP snapshot contains servers not declared by extension bindings"
        )
    for skill in skills_config.skills:
        if skill.skill_id not in bound_skill_ids:
            raise PackageDistributionError(
                "distribution Skill snapshot contains Skills not declared by extension bindings"
            )
        source = _distribution_skill_source(root, skill)
        try:
            importable = parse_skill_directory(
                source,
                allow_directory_name_mismatch=True,
                allow_missing_frontmatter=True,
                fallback_name=skill.skill_id,
            )
        except Exception as exc:
            raise PackageDistributionError(
                f"distributed Skill is invalid: {skill.skill_id}"
            ) from exc
        if importable.name != skill.skill_id:
            raise PackageDistributionError(
                f"distributed Skill identity mismatch: "
                f"{skill.skill_id} != {importable.name}"
            )


def _distribution_skill_source(
    root: Path,
    skill: Any,
) -> Path:
    relative = PurePosixPath(str(skill.path or ""))
    expected_prefix = PurePosixPath(EXTENSION_DISTRIBUTION_SKILLS_DIR)
    if (
        relative.is_absolute()
        or "\\" in str(skill.path)
        or not relative.parts
        or PurePosixPath(*relative.parts[:1]) != expected_prefix
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise PackageDistributionError(
            f"distributed Skill path is invalid: {skill.skill_id}"
        )
    source = (root / "extensions" / Path(*relative.parts)).resolve()
    extension_root = (root / "extensions").resolve()
    try:
        source.relative_to(extension_root)
    except ValueError as exc:
        raise PackageDistributionError(
            f"distributed Skill path escapes package: {skill.skill_id}"
        ) from exc
    if not (source / "SKILL.md").is_file():
        raise PackageDistributionError(
            f"distributed Skill content is missing: {skill.skill_id}"
        )
    return source


def _skill_file_inventory(root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            files.append(
                {
                    "path": relative,
                    "size_bytes": size,
                    "kind": "binary",
                    "included": True,
                    "content": None,
                }
            )
        else:
            files.append(
                {
                    "path": relative,
                    "size_bytes": size,
                    "kind": "text",
                    "included": True,
                    "content": content,
                }
            )
    return files


def _safe_skill_file_path(value: Any) -> str:
    text = str(value or "").strip()
    path = PurePosixPath(text)
    if (
        not text
        or "\\" in text
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PackageDistributionError(f"invalid Skill file path: {text!r}")
    return path.as_posix()


def _is_distribution_local_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    return (
        any(part in DISTRIBUTION_LOCAL_PARTS for part in path.parts)
        or path.name in DISTRIBUTION_LOCAL_NAMES
        or path.name.startswith(".env.")
        or any(path.name.endswith(suffix) for suffix in DISTRIBUTION_LOCAL_SUFFIXES)
    )


def _add_manifest_file(files: set[str], value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    relative = normalize_package_relative(value)
    if relative and not is_transient_package_path(relative):
        files.add(relative)


def _add_asset_dir_for_manifest_path(dirs: set[str], value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    relative = normalize_package_relative(value)
    parts = relative.split("/")
    if parts and parts[0] in PACKAGE_ASSET_DIRS:
        dirs.add(parts[0] if len(parts) == 1 else "/".join(parts[:-1]))
