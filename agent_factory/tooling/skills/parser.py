from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from ruamel.yaml import YAML

from agent_factory.tooling.skills.schema import (
    SkillMetadata,
    SkillPackage,
    SkillResourceRef,
    SkillScriptRef,
)


RESOURCE_DIR_KINDS = {
    "references": "reference",
    "templates": "template",
    "examples": "example",
    "assets": "asset",
}
TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".conf",
    ".csv",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
MAX_SKILL_BODY_CHARS = 80000


def parse_skill_directory(
    skill_root: str | Path,
    *,
    allow_directory_name_mismatch: bool = False,
    allow_missing_frontmatter: bool = False,
    fallback_name: str | None = None,
) -> SkillPackage:
    root = Path(skill_root).expanduser().resolve()
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"SKILL.md not found: {skill_md}")
    text = skill_md.read_text(encoding="utf-8").replace("\r\n", "\n")
    if text.startswith("---\n"):
        frontmatter, body = _parse_frontmatter(text)
    elif allow_missing_frontmatter:
        body = text
        frontmatter = {
            "name": fallback_name or root.name,
            "description": _infer_description_from_body(text, fallback_name or root.name),
        }
    else:
        raise ValueError("SKILL.md must start with YAML frontmatter")
    metadata = SkillMetadata.model_validate(frontmatter)
    if not allow_directory_name_mismatch and root.name != metadata.name:
        raise ValueError(f"skill directory name must match frontmatter name: {root.name} != {metadata.name}")
    if len(body) > MAX_SKILL_BODY_CHARS:
        raise ValueError(f"SKILL.md body exceeds {MAX_SKILL_BODY_CHARS} characters: {skill_md}")
    return SkillPackage(
        metadata=metadata,
        root=str(root),
        skill_md_path=str(skill_md),
        body=body.strip(),
        resources=_discover_resources(root),
        scripts=_discover_scripts(root, metadata.name),
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md frontmatter must be closed with ---")
    yaml = YAML(typ="safe")
    frontmatter = yaml.load(text[4:end]) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    return dict(frontmatter), text[end + 5 :]


def _infer_description_from_body(text: str, fallback_name: str) -> str:
    lines = [line.strip(" #*\t") for line in text.splitlines()]
    for line in lines:
        if not line or line.startswith("---"):
            continue
        if re.match(r"^[\w\s-]+:\s*$", line):
            continue
        return line[:1024]
    return f"SkillHub skill: {fallback_name}"


def _discover_resources(root: Path) -> list[SkillResourceRef]:
    discovered: list[tuple[Path, str]] = []
    for directory, kind in RESOURCE_DIR_KINDS.items():
        base = root / directory
        if not base.is_dir():
            continue
        for path in (item for item in base.rglob("*") if item.is_file()):
            discovered.append((path, kind))
    refs: list[SkillResourceRef] = []
    for path, kind in sorted(discovered, key=lambda item: _resource_sort_key(item[0])):
        _assert_inside(root, path)
        refs.append(
            SkillResourceRef(
                path=path.relative_to(root).as_posix(),
                kind=kind,
                media_type=_media_type(path),
                size_bytes=path.stat().st_size,
                readable=_is_text_resource(path),
            )
        )
    return refs


def _resource_sort_key(path: Path) -> tuple[int, str]:
    relative = path.as_posix()
    name = path.name
    if "/examples/" in relative or relative.endswith(".capability.json"):
        group = 0
    elif name.endswith(".repair_hints.md") or name.endswith(".common_errors.md") or name.endswith(".validator_scope.md"):
        group = 1
    elif name.endswith(".schema.json"):
        group = 3
    else:
        group = 2
    return (group, relative)


def _discover_scripts(root: Path, skill_name: str) -> list[SkillScriptRef]:
    scripts_root = root / "scripts"
    if not scripts_root.is_dir():
        return []
    scripts: list[SkillScriptRef] = []
    for path in sorted(item for item in scripts_root.rglob("*") if item.is_file()):
        _assert_inside(root, path)
        relative = path.relative_to(root).as_posix()
        scripts.append(
            SkillScriptRef(
                path=relative,
                script_ref=f"skill://{skill_name}/{relative}",
                resolved_path=str(path),
                size_bytes=path.stat().st_size,
            )
        )
    return scripts


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return "text/markdown" if suffix == ".md" else "text/plain"
    if suffix == ".json":
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".py":
        return "text/x-python"
    return "text/plain" if _is_text_resource(path) else "application/octet-stream"


def _is_text_resource(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Skill path escapes skill root: {path}") from exc
