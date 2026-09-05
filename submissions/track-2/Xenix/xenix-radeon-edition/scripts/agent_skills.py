from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PROJECT_ROOT / "src" / "xenix" / "services" / "agent" / "skills"
CATALOG_PATH = SKILLS_ROOT / "catalog.json"
SKILL_FILE_NAME = "SKILL.md"
CATALOG_SCHEMA_VERSION = 1
MAX_RESOURCE_BYTES = 64 * 1024


@dataclass(frozen=True)
class ParsedSkill:
    name: str
    description: str
    body: str
    directory: str
    skill_file: str
    metadata: dict[str, Any]
    resources: dict[str, dict[str, str]]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or generate the static Xenix Agent Skill catalog.")
    parser.add_argument("command", choices=["check", "generate"])
    args = parser.parse_args()

    catalog = build_catalog()
    if args.command == "generate":
        CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CATALOG_PATH.write_text(_catalog_text(catalog), encoding="utf-8")
        print(f"Generated {CATALOG_PATH.relative_to(PROJECT_ROOT)} with {len(catalog['skills'])} skill(s).")
        return 0

    if not CATALOG_PATH.exists():
        print(f"Missing {CATALOG_PATH.relative_to(PROJECT_ROOT)}. Run `pdm run agent-skills-generate`.")
        return 1
    existing = CATALOG_PATH.read_text(encoding="utf-8")
    expected = _catalog_text(catalog)
    if existing != expected:
        print(f"{CATALOG_PATH.relative_to(PROJECT_ROOT)} is out of date. Run `pdm run agent-skills-generate`.")
        return 1
    print(f"Checked {CATALOG_PATH.relative_to(PROJECT_ROOT)} with {len(catalog['skills'])} skill(s).")
    return 0


def build_catalog() -> dict[str, Any]:
    skills = [_skill_to_catalog_entry(skill) for skill in _load_skills()]
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "skills": skills,
    }


def _load_skills() -> list[ParsedSkill]:
    if not SKILLS_ROOT.exists():
        return []

    skills: list[ParsedSkill] = []
    seen_names: set[str] = set()
    for skill_dir in sorted(path for path in SKILLS_ROOT.iterdir() if _is_skill_directory(path)):
        skill_file = skill_dir / SKILL_FILE_NAME
        if not skill_file.exists():
            raise SystemExit(f"Skill directory {skill_dir.relative_to(PROJECT_ROOT)} is missing {SKILL_FILE_NAME}.")
        skill = _parse_skill(skill_dir, skill_file)
        if skill.name in seen_names:
            raise SystemExit(f"Duplicate skill name: {skill.name}")
        seen_names.add(skill.name)
        skills.append(skill)
    return skills


def _is_skill_directory(path: Path) -> bool:
    return path.is_dir() and not path.name.startswith(".") and path.name != "__pycache__"


def _parse_skill(skill_dir: Path, skill_file: Path) -> ParsedSkill:
    text = skill_file.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text, skill_file)
    metadata = _parse_yaml(frontmatter, skill_file)
    name = _required_string(metadata, "name", skill_file)
    description = _required_string(metadata, "description", skill_file)
    if name != skill_dir.name:
        raise SystemExit(
            f"{skill_file.relative_to(PROJECT_ROOT)} frontmatter name must match its directory name: {skill_dir.name}"
        )
    if not body.strip():
        raise SystemExit(f"{skill_file.relative_to(PROJECT_ROOT)} body cannot be empty.")
    return ParsedSkill(
        name=name,
        description=description,
        body=body.strip() + "\n",
        directory=skill_dir.name,
        skill_file=f"{skill_dir.name}/{SKILL_FILE_NAME}",
        metadata=metadata,
        resources=_resource_manifest(skill_dir),
    )


def _resource_manifest(skill_dir: Path) -> dict[str, dict[str, str]]:
    return {
        "references": _resource_map(skill_dir, "references"),
        "assets": _resource_map(skill_dir, "assets"),
    }


def _resource_map(skill_dir: Path, directory_name: str) -> dict[str, str]:
    root = skill_dir / directory_name
    if not root.exists():
        return {}
    if not root.is_dir():
        raise SystemExit(f"{root.relative_to(PROJECT_ROOT)} must be a directory.")

    resources: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(skill_dir).parts
        if any(part.startswith(".") or part == "__pycache__" for part in relative_parts):
            continue
        relative_path = path.relative_to(skill_dir).as_posix()
        data = path.read_bytes()
        if len(data) > MAX_RESOURCE_BYTES:
            raise SystemExit(
                f"{path.relative_to(PROJECT_ROOT)} exceeds the Agent Skill resource limit "
                f"of {MAX_RESOURCE_BYTES} bytes."
            )
        try:
            resources[relative_path] = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SystemExit(f"{path.relative_to(PROJECT_ROOT)} must be UTF-8 text.") from exc
    return resources


def _split_frontmatter(text: str, skill_file: Path) -> tuple[str, str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise SystemExit(f"{skill_file.relative_to(PROJECT_ROOT)} must start with YAML frontmatter.")
    closing_index = normalized.find("\n---\n", 4)
    if closing_index == -1:
        raise SystemExit(f"{skill_file.relative_to(PROJECT_ROOT)} has no closing YAML frontmatter marker.")
    frontmatter = normalized[4:closing_index]
    body = normalized[closing_index + len("\n---\n") :]
    return frontmatter, body


def _parse_yaml(frontmatter: str, skill_file: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise SystemExit("PyYAML is required for Agent Skill catalog generation. Run `pdm install`.") from exc

    data = yaml.safe_load(frontmatter)
    if not isinstance(data, dict):
        raise SystemExit(f"{skill_file.relative_to(PROJECT_ROOT)} frontmatter must be a YAML object.")
    return dict(data)


def _required_string(metadata: dict[str, Any], key: str, skill_file: Path) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{skill_file.relative_to(PROJECT_ROOT)} frontmatter field `{key}` must be a non-empty string.")
    return value.strip()


def _skill_to_catalog_entry(skill: ParsedSkill) -> dict[str, Any]:
    return {
        "name": skill.name,
        "description": skill.description,
        "body": skill.body,
        "directory": skill.directory,
        "skill_file": skill.skill_file,
        "metadata": skill.metadata,
        "resources": skill.resources,
    }


def _catalog_text(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
