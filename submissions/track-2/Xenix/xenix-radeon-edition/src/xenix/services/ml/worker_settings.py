from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from ...config import AppPaths

SETTINGS_FILE_NAME = "ml_workers.json"
DEFAULT_LOCAL_WORKER_ID = "local"

_WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MLWorkerKind(StrEnum):
    LOCAL = "local"
    SSH = "ssh"


class MLWorkerSetupState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    READY = "ready"
    FAILED = "failed"


class MLWorkerValidationStatus(StrEnum):
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MLWorkerValidationRecord(BaseModel):
    status: MLWorkerValidationStatus = MLWorkerValidationStatus.UNKNOWN
    checked_at: str | None = None
    summary: str = ""
    details: list[str] = Field(default_factory=list)


class MLWorkerConfig(BaseModel):
    id: str
    display_name: str
    kind: MLWorkerKind
    enabled: bool = True
    weight: int = Field(default=100, ge=1, le=1000)
    max_concurrent_tasks: int = Field(default=1, ge=1, le=32)
    capabilities: list[str] = Field(default_factory=list)
    host: str = ""
    user: str = ""
    port: int = Field(default=22, ge=1, le=65535)
    ssh_alias: str = ""
    identity_file_path: str = ""
    remote_root: str = "~/.xenix/workers"
    python_command: str = "python3"
    setup_state: MLWorkerSetupState = MLWorkerSetupState.NOT_CONFIGURED
    last_validation: MLWorkerValidationRecord = Field(default_factory=MLWorkerValidationRecord)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        worker_id = value.strip()
        if not worker_id:
            raise ValueError("Worker id cannot be empty.")
        if not _WORKER_ID_PATTERN.fullmatch(worker_id):
            raise ValueError("Worker id may contain only letters, numbers, dots, underscores, and dashes.")
        return worker_id

    @field_validator("display_name", "host", "user", "ssh_alias", "identity_file_path", "remote_root", "python_command")
    @classmethod
    def _strip_string(cls, value: str) -> str:
        return value.strip()

    @field_validator("capabilities")
    @classmethod
    def _normalize_capabilities(cls, value: list[str]) -> list[str]:
        capabilities: list[str] = []
        seen: set[str] = set()
        for raw_capability in value:
            capability = str(raw_capability).strip()
            if capability and capability not in seen:
                capabilities.append(capability)
                seen.add(capability)
        return capabilities

    @model_validator(mode="after")
    def _validate_worker(self) -> MLWorkerConfig:
        if not self.display_name:
            self.display_name = self.id
        if self.kind is MLWorkerKind.LOCAL:
            if not self.python_command:
                self.python_command = "python"
            return self
        if self.kind is MLWorkerKind.SSH:
            if not self.ssh_alias and not self.host:
                raise ValueError("SSH worker requires an SSH alias or host.")
            if not self.remote_root:
                raise ValueError("SSH worker requires a remote root.")
            if not self.python_command:
                raise ValueError("SSH worker requires a Python command.")
            return self
        return self

    @property
    def target(self) -> str:
        if self.ssh_alias:
            return self.ssh_alias
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host


class MLWorkerPoolConfig(BaseModel):
    enabled: bool = True
    selection_policy: str = "least_busy"
    max_concurrent_tasks: int = Field(default=32, ge=1, le=32)
    local_worker_enabled: bool = True


class MLWorkerSettings(BaseModel):
    schema_version: int = 1
    pool: MLWorkerPoolConfig = Field(default_factory=MLWorkerPoolConfig)
    workers: list[MLWorkerConfig] = Field(default_factory=lambda: [_default_local_worker()])

    @model_validator(mode="after")
    def _validate_workers(self) -> MLWorkerSettings:
        if not self.workers:
            self.workers = [_default_local_worker()]
        seen: set[str] = set()
        for worker in self.workers:
            if worker.id in seen:
                raise ValueError(f"Worker id '{worker.id}' is duplicated.")
            seen.add(worker.id)
        if self.pool.local_worker_enabled and not any(worker.kind is MLWorkerKind.LOCAL for worker in self.workers):
            self.workers.insert(
                0,
                _default_local_worker(),
            )
        return self


class MLWorkerSettingsService:
    def __init__(self, paths: AppPaths) -> None:
        self._settings_path = paths.config / SETTINGS_FILE_NAME

    @property
    def settings_path(self) -> Path:
        return self._settings_path

    def load(self) -> MLWorkerSettings:
        if not self._settings_path.exists():
            return MLWorkerSettings()
        payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
        return MLWorkerSettings.model_validate(payload)

    def save(self, settings: MLWorkerSettings) -> None:
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(
            settings.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def add_or_update_worker(self, worker: MLWorkerConfig) -> MLWorkerSettings:
        settings = self.load()
        updated = False
        workers: list[MLWorkerConfig] = []
        for existing in settings.workers:
            if existing.id == worker.id:
                workers.append(worker)
                updated = True
            else:
                workers.append(existing)
        if not updated:
            workers.append(worker)
        settings.workers = workers
        self.save(settings)
        return settings


def generate_worker_id(prefix: str = "xenix.ssh") -> str:
    return f"{prefix}.{uuid4().hex[:8]}"


def validation_record(
    status: MLWorkerValidationStatus,
    summary: str,
    details: list[str] | None = None,
) -> MLWorkerValidationRecord:
    return MLWorkerValidationRecord(
        status=status,
        checked_at=utc_now_iso(),
        summary=summary,
        details=list(details or []),
    )


def _default_local_worker() -> MLWorkerConfig:
    return MLWorkerConfig(
        id=DEFAULT_LOCAL_WORKER_ID,
        display_name="This computer",
        kind=MLWorkerKind.LOCAL,
        setup_state=MLWorkerSetupState.READY,
        last_validation=MLWorkerValidationRecord(
            status=MLWorkerValidationStatus.SUCCEEDED,
            summary="Local worker is available.",
        ),
    )
