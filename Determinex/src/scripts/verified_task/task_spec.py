"""Canonical benchmark task contract for Determinex verifier loops."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ScorerKind = Literal[
    "all_commands_pass",
    "programbench_passed_total",
    "custom",
]


@dataclass(slots=True)
class ResourceLimits:
    timeout_seconds: int = 600
    max_attempts: int = 3
    max_parallel: int = 1
    docker_cpus: int = 1
    memory_mb: int | None = None
    disk_mb: int | None = None


@dataclass(slots=True)
class TaskSpec:
    id: str
    benchmark: str
    language: str
    instruction: str
    repo_or_workspace: str | None = None
    prompt: str | None = None
    hidden_tests: list[str] = field(default_factory=list)
    public_tests: list[str] = field(default_factory=list)
    allowed_files: list[str] = field(default_factory=list)
    forbidden_files: list[str] = field(default_factory=list)
    setup_commands: list[str] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)
    expected_outputs: dict[str, Any] = field(default_factory=dict)
    scorer: ScorerKind = "all_commands_pass"
    privacy_policy: str = "local"
    cloak_mode: str = "off"
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSpec:
        payload = dict(data)
        limits = payload.get("resource_limits") or {}
        if isinstance(limits, ResourceLimits):
            payload["resource_limits"] = limits
        else:
            payload["resource_limits"] = ResourceLimits(**limits)
        return cls(**payload)

    def validate(self) -> None:
        if not self.id.strip():
            raise ValueError("TaskSpec.id is required")
        if not self.benchmark.strip():
            raise ValueError("TaskSpec.benchmark is required")
        if not self.validation_commands and self.scorer == "all_commands_pass":
            raise ValueError("all_commands_pass tasks require validation_commands")
        if self.repo_or_workspace:
            path = Path(self.repo_or_workspace)
            if not path.exists():
                raise ValueError(f"repo_or_workspace does not exist: {path}")
