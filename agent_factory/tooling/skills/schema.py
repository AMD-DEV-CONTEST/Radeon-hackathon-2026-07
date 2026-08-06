from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_factory.tooling.builtins.aliases import canonical_builtin_tool_id


SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillResourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    kind: Literal["reference", "template", "example", "asset"]
    media_type: str = "text/plain"
    size_bytes: int = 0
    readable: bool = True


class SkillScriptRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    script_ref: str
    resolved_path: str
    execution_tool: Literal["shell"] = "shell"
    size_bytes: int = 0

    @field_validator("execution_tool", mode="before")
    @classmethod
    def _canonicalize_execution_tool(cls, value: Any) -> str:
        return canonical_builtin_tool_id(str(value or "shell"))


class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    license: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not SKILL_NAME_PATTERN.fullmatch(value):
            raise ValueError("skill name must use lowercase kebab-case")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("skill description must be non-empty")
        if len(text) > 1024:
            raise ValueError("skill description must be at most 1024 characters")
        return text


class SkillPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: SkillMetadata
    root: str
    skill_md_path: str
    body: str
    resources: list[SkillResourceRef] = Field(default_factory=list)
    scripts: list[SkillScriptRef] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return self.metadata.name


class SkillLoadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    metadata: SkillMetadata
    content: str
    resources: list[SkillResourceRef] = Field(default_factory=list)
    scripts: list[SkillScriptRef] = Field(default_factory=list)
    resource_contents: dict[str, str] = Field(default_factory=dict)


class SkillLoadRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    reason: str
    loaded_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    primary: bool = False


class SkillResourceReadRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    mode: str = "outline"
    pointer: str = ""
    digest: str = ""
    read_count: int = 1
    first_read_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_read_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SkillSystemLoadState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_system: str
    primary_skill: str = ""
    described_skills: list[str] = Field(default_factory=list)
    loaded_skills: list[SkillLoadRecord] = Field(default_factory=list)
    read_resources: list[SkillResourceReadRecord] = Field(default_factory=list)

    def has_seen(self, name: str) -> bool:
        return name in self.described_skills or any(item.name == name for item in self.loaded_skills)

    def mark_described(self, name: str) -> None:
        if name not in self.described_skills:
            self.described_skills.append(name)
            self.described_skills.sort()

    def mark_loaded(self, name: str, *, reason: str) -> None:
        if not self.primary_skill:
            self.primary_skill = name
        if any(item.name == name for item in self.loaded_skills):
            return
        self.loaded_skills.append(
            SkillLoadRecord(
                name=name,
                reason=reason,
                primary=name == self.primary_skill,
            )
        )

    def resource_read_record(self, name: str, path: str, *, mode: str, pointer: str) -> SkillResourceReadRecord | None:
        for record in self.read_resources:
            if record.name == name and record.path == path and record.mode == mode and record.pointer == pointer:
                return record
        return None

    def mark_resource_read(self, name: str, path: str, *, mode: str, pointer: str, digest: str) -> SkillResourceReadRecord:
        existing = self.resource_read_record(name, path, mode=mode, pointer=pointer)
        now = datetime.now(UTC).isoformat()
        if existing is not None:
            updated = existing.model_copy(
                update={
                    "digest": digest,
                    "read_count": existing.read_count + 1,
                    "last_read_at": now,
                }
            )
            self.read_resources = [
                updated if item is existing else item
                for item in self.read_resources
            ]
            return updated
        record = SkillResourceReadRecord(
            name=name,
            path=path,
            mode=mode,
            pointer=pointer,
            digest=digest,
            first_read_at=now,
            last_read_at=now,
        )
        self.read_resources.append(record)
        self.read_resources.sort(key=lambda item: (item.name, item.path, item.mode, item.pointer))
        return record


class SkillGatewayState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["skill_gateway_state.v0"] = "skill_gateway_state.v0"
    by_system: dict[str, SkillSystemLoadState] = Field(default_factory=dict)

    def system_state(self, current_system: str) -> SkillSystemLoadState:
        state = self.by_system.get(current_system)
        if state is None:
            state = SkillSystemLoadState(current_system=current_system)
            self.by_system[current_system] = state
        return state
