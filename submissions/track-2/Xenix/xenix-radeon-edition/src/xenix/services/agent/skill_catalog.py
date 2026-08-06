from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from ...exceptions import NotFoundError, ValidationError
from ..llm.providers import ProviderMessage
from ..llm.tooling import AgentTool, AgentToolSpec, ToolExecutionContext, ToolSuccess
from .tool_inputs import AgentSkillActivateInput, AgentSkillResourceInput


AGENT_SKILL_ACTIVATE_TOOL_NAME = "agent.skill.activate"
AGENT_SKILL_ACTIVATE_PROVIDER_NAME = "agent_skill_activate"
AGENT_SKILL_READ_REFERENCE_TOOL_NAME = "agent.skill.read_reference"
AGENT_SKILL_READ_REFERENCE_PROVIDER_NAME = "agent_skill_read_reference"
AGENT_SKILL_READ_ASSET_TOOL_NAME = "agent.skill.read_asset"
AGENT_SKILL_READ_ASSET_PROVIDER_NAME = "agent_skill_read_asset"
AGENT_SKILL_CATALOG_SCHEMA_VERSION = 1
MAX_AGENT_SKILL_RESOURCE_BYTES = 64 * 1024


@dataclass(frozen=True)
class AgentSkill:
    name: str
    description: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, dict[str, str]] = field(default_factory=dict)


class AgentSkillCatalog:
    def __init__(self, skills: list[AgentSkill] | None = None) -> None:
        self._skills = {skill.name: skill for skill in skills or []}
        if len(self._skills) != len(skills or []):
            raise ValidationError("Agent Skill catalog contains duplicate skill names.")

    @classmethod
    def from_default_catalog(cls) -> "AgentSkillCatalog":
        return cls.from_catalog_path(_default_catalog_path())

    @classmethod
    def from_catalog_path(cls, catalog_path: Path) -> "AgentSkillCatalog":
        if not catalog_path.exists():
            return cls([])
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValidationError("Agent Skill catalog must be a JSON object.")
        if raw.get("schema_version") != AGENT_SKILL_CATALOG_SCHEMA_VERSION:
            raise ValidationError("Agent Skill catalog schema version is unsupported.")
        raw_skills = raw.get("skills")
        if not isinstance(raw_skills, list):
            raise ValidationError("Agent Skill catalog skills must be a list.")
        return cls([_skill_from_catalog_entry(entry) for entry in raw_skills])

    def has_skills(self) -> bool:
        return bool(self._skills)

    def list_skills(self) -> list[AgentSkill]:
        return [self._skills[name] for name in sorted(self._skills)]

    def catalog_provider_message(self, *, activated_skill_names: set[str] | None = None) -> ProviderMessage | None:
        if not self._skills:
            return None
        activated = set(activated_skill_names or set())
        entries = [
            {
                "name": skill.name,
                "description": skill.description,
                "active": skill.name in activated,
                "reference_count": len(skill.resources.get("references", [])),
                "asset_count": len(skill.resources.get("assets", [])),
            }
            for skill in self.list_skills()
        ]
        content = (
            "Xenix Agent Skills are prompt instructions only, never plugins, scripts, filesystem access, or external "
            "extensions. For a matching inactive skill, call "
            f"`{AGENT_SKILL_ACTIVATE_TOOL_NAME}` before proceeding; do not activate unrelated skills and follow its "
            "returned instructions. After activation, read only a listed needed resource with "
            f"`{AGENT_SKILL_READ_REFERENCE_TOOL_NAME}` or `{AGENT_SKILL_READ_ASSET_TOOL_NAME}`.\n"
            "<available_agent_skills>"
            f"{json.dumps(entries, ensure_ascii=False, separators=(',', ':'))}"
            "</available_agent_skills>"
        )
        return ProviderMessage(role="system", content=content)

    def activation_tool_spec(self, *, activated_skill_names: set[str] | None = None) -> AgentToolSpec | None:
        tool = self.activation_tool(activated_skill_names=activated_skill_names)
        return tool.spec if tool is not None else None

    def activation_tool(
        self,
        *,
        activated_skill_names: set[str] | None = None,
    ) -> AgentTool[AgentSkillActivateInput] | None:
        inactive_names = [
            skill.name
            for skill in self.list_skills()
            if skill.name not in set(activated_skill_names or set())
        ]
        if not inactive_names:
            return None

        def activate(
            input_data: AgentSkillActivateInput,
            _context: ToolExecutionContext,
        ) -> ToolSuccess:
            return ToolSuccess(self.activate(input_data.name))

        return AgentTool(
            name=AGENT_SKILL_ACTIVATE_TOOL_NAME,
            provider_name=AGENT_SKILL_ACTIVATE_PROVIDER_NAME,
            description=(
                "Activate one built-in Xenix Agent Skill when the user task matches its description. "
                "This returns prompt instructions only; it does not execute scripts or read arbitrary files."
            ),
            input_model=AgentSkillActivateInput,
            implementation=activate,
            provider_field_enums=(("name", tuple(inactive_names)),),
        )

    def resource_tool_specs(self, *, activated_skill_names: set[str] | None = None) -> list[AgentToolSpec]:
        tools = self.resource_tools(
            activated_skill_names=activated_skill_names,
            active_skill_names_provider=lambda _context: set(
                activated_skill_names or set()
            ),
        )
        return [tool.spec for tool in tools]

    def resource_tools(
        self,
        *,
        activated_skill_names: set[str] | None = None,
        active_skill_names_provider: Callable[[ToolExecutionContext], set[str]],
    ) -> list[AgentTool[AgentSkillResourceInput]]:
        activated = set(activated_skill_names or set())
        active_skills = [skill for skill in self.list_skills() if skill.name in activated]
        tools: list[AgentTool[AgentSkillResourceInput]] = []
        if any(skill.resources.get("references") for skill in active_skills):
            tools.append(
                self._resource_tool(
                    tool_name=AGENT_SKILL_READ_REFERENCE_TOOL_NAME,
                    provider_name=AGENT_SKILL_READ_REFERENCE_PROVIDER_NAME,
                    description=(
                        "Read one reference listed by an already activated Xenix Agent Skill. "
                        "This returns only UTF-8 reference text embedded in the generated catalog."
                    ),
                    skill_names=[skill.name for skill in active_skills if skill.resources.get("references")],
                    resource_reader=self.read_reference,
                    active_skill_names_provider=active_skill_names_provider,
                )
            )
        if any(skill.resources.get("assets") for skill in active_skills):
            tools.append(
                self._resource_tool(
                    tool_name=AGENT_SKILL_READ_ASSET_TOOL_NAME,
                    provider_name=AGENT_SKILL_READ_ASSET_PROVIDER_NAME,
                    description=(
                        "Read one asset listed by an already activated Xenix Agent Skill. "
                        "This returns only UTF-8 asset text embedded in the generated catalog."
                    ),
                    skill_names=[skill.name for skill in active_skills if skill.resources.get("assets")],
                    resource_reader=self.read_asset,
                    active_skill_names_provider=active_skill_names_provider,
                )
            )
        return tools

    def _resource_tool(
        self,
        *,
        tool_name: str,
        provider_name: str,
        description: str,
        skill_names: list[str],
        resource_reader: Callable[..., dict[str, Any]],
        active_skill_names_provider: Callable[[ToolExecutionContext], set[str]],
    ) -> AgentTool[AgentSkillResourceInput]:
        def read_resource(
            input_data: AgentSkillResourceInput,
            context: ToolExecutionContext,
        ) -> ToolSuccess:
            return ToolSuccess(
                resource_reader(
                    skill_name=input_data.skill_name,
                    path=input_data.path,
                    activated_skill_names=active_skill_names_provider(context),
                )
            )

        return AgentTool(
            name=tool_name,
            provider_name=provider_name,
            description=description,
            input_model=AgentSkillResourceInput,
            implementation=read_resource,
            provider_field_enums=(("skill_name", tuple(skill_names)),),
        )

    def activate(self, skill_name: str) -> dict[str, Any]:
        normalized = skill_name.strip()
        skill = self._skills.get(normalized)
        if skill is None:
            raise NotFoundError(f"Agent Skill '{skill_name}' was not found.")
        return {
            "skill_name": skill.name,
            "description": skill.description,
            "instructions": skill.body,
            "metadata": dict(skill.metadata),
            "resources": {key: sorted(value) for key, value in skill.resources.items()},
        }

    def read_reference(
        self,
        *,
        skill_name: str,
        path: str,
        activated_skill_names: set[str] | None = None,
    ) -> dict[str, Any]:
        return self._read_resource(
            kind="references",
            skill_name=skill_name,
            path=path,
            activated_skill_names=activated_skill_names,
        )

    def read_asset(
        self,
        *,
        skill_name: str,
        path: str,
        activated_skill_names: set[str] | None = None,
    ) -> dict[str, Any]:
        return self._read_resource(
            kind="assets",
            skill_name=skill_name,
            path=path,
            activated_skill_names=activated_skill_names,
        )

    def _read_resource(
        self,
        *,
        kind: str,
        skill_name: str,
        path: str,
        activated_skill_names: set[str] | None,
    ) -> dict[str, Any]:
        normalized_skill_name = skill_name.strip()
        skill = self._skills.get(normalized_skill_name)
        if skill is None:
            raise NotFoundError(f"Agent Skill '{skill_name}' was not found.")

        activated = {
            name.strip()
            for name in (activated_skill_names or set())
            if isinstance(name, str) and name.strip()
        }
        if skill.name not in activated:
            raise ValidationError(
                f"Agent Skill '{skill.name}' must be activated in this Thread before reading resources.",
                error_code="agent_skill_not_activated",
            )

        normalized_path = _normalize_resource_path(path)
        resources = skill.resources.get(kind, {})
        content = resources.get(normalized_path)
        if content is None:
            raise ValidationError(
                f"Agent Skill resource '{normalized_path}' is not listed for skill '{skill.name}'."
            )
        data = content.encode("utf-8")
        if len(data) > MAX_AGENT_SKILL_RESOURCE_BYTES:
            raise ValidationError(
                f"Agent Skill resource '{normalized_path}' exceeds "
                f"{MAX_AGENT_SKILL_RESOURCE_BYTES} bytes."
            )

        return {
            "skill_name": skill.name,
            "kind": kind,
            "path": normalized_path,
            "content": content,
            "size_bytes": len(data),
        }


def is_agent_skill_tool(tool_name: str) -> bool:
    return tool_name.startswith("agent.skill.")


def _default_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "skills" / "catalog.json"


def _skill_from_catalog_entry(entry: Any) -> AgentSkill:
    if not isinstance(entry, dict):
        raise ValidationError("Agent Skill catalog entries must be objects.")
    name = _required_string(entry, "name")
    description = _required_string(entry, "description")
    body = _required_string(entry, "body")
    metadata = entry.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValidationError(f"Agent Skill '{name}' metadata must be an object.")
    resources = _resources_from_catalog_entry(entry, name)
    return AgentSkill(
        name=name,
        description=description,
        body=body,
        metadata=dict(metadata),
        resources=resources,
    )


def _required_string(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"Agent Skill catalog field '{key}' must be a non-empty string.")
    return value.strip()


def _resources_from_catalog_entry(entry: dict[str, Any], skill_name: str) -> dict[str, dict[str, str]]:
    raw = entry.get("resources")
    if raw is None:
        return {"references": {}, "assets": {}}
    if not isinstance(raw, dict):
        raise ValidationError(f"Agent Skill '{skill_name}' resources must be an object.")
    resources: dict[str, dict[str, str]] = {}
    for key in ("references", "assets"):
        values = raw.get(key, {})
        if not isinstance(values, dict):
            raise ValidationError(f"Agent Skill '{skill_name}' resources.{key} must be an object.")
        normalized_values: dict[str, str] = {}
        for raw_path, content in values.items():
            if not isinstance(raw_path, str):
                raise ValidationError(f"Agent Skill '{skill_name}' resources.{key} paths must be strings.")
            if not isinstance(content, str):
                raise ValidationError(f"Agent Skill '{skill_name}' resources.{key} content must be strings.")
            normalized_path = _normalize_resource_path(raw_path)
            if normalized_path in normalized_values:
                raise ValidationError(
                    f"Agent Skill '{skill_name}' resources.{key} contains duplicate path '{normalized_path}'."
                )
            if len(content.encode("utf-8")) > MAX_AGENT_SKILL_RESOURCE_BYTES:
                raise ValidationError(
                    f"Agent Skill '{skill_name}' resource '{normalized_path}' exceeds "
                    f"{MAX_AGENT_SKILL_RESOURCE_BYTES} bytes."
                )
            normalized_values[normalized_path] = content
        resources[key] = normalized_values
    return resources


def _normalize_resource_path(raw_path: str) -> str:
    path = str(raw_path).replace("\\", "/").strip()
    if not path:
        raise ValidationError("Agent Skill resource path must be a non-empty relative path.")
    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
        raise ValidationError("Agent Skill resource path must stay within its skill directory.")
    return pure_path.as_posix()
