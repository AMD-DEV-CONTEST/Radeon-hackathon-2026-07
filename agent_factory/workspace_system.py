from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.paths import factory_artifact_path
from agent_factory.workspace_mounts import WorkspaceMountRecord


WorkspaceMode = Literal["isolated", "project"]
WorkspaceRootKind = Literal["managed", "linked"]


class WorkspaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    title: str
    mode: WorkspaceMode = "isolated"
    root_kind: WorkspaceRootKind = "managed"
    owner_package_id: str | None = None
    workdir_root: str
    mounts: list[WorkspaceMountRecord] = Field(default_factory=list)
    archived: bool = False
    created_at: str
    updated_at: str


class WorkspaceStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or factory_artifact_path("workspaces")).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        title: str | None = None,
        mode: WorkspaceMode = "isolated",
        root_kind: WorkspaceRootKind = "managed",
        owner_package_id: str | None = None,
        workspace_id: str | None = None,
        workdir_root: Path | None = None,
    ) -> WorkspaceRecord:
        identifier = _identifier(workspace_id or uuid4().hex)
        if self.exists(identifier):
            raise ValueError(f"Workspace already exists: {identifier}")
        now = datetime.now(UTC).isoformat()
        if root_kind == "linked" and workdir_root is None:
            raise ValueError("linked workspace requires workdir_root")
        resolved_workdir = _workspace_root_path(
            workdir_root,
            default=self.root / identifier / "workdir",
            require_existing=root_kind == "linked",
        )
        resolved_workdir.mkdir(parents=True, exist_ok=True)
        record = WorkspaceRecord(
            workspace_id=identifier,
            title=str(title or "").strip() or "新工作区",
            mode=mode,
            root_kind=root_kind,
            owner_package_id=str(owner_package_id or "").strip() or None,
            workdir_root=str(resolved_workdir),
            created_at=now,
            updated_at=now,
        )
        self.save(record)
        return record

    def load(self, workspace_id: str) -> WorkspaceRecord:
        path = self._record_path(workspace_id)
        if not path.is_file():
            raise FileNotFoundError(f"Workspace not found: {workspace_id}")
        return WorkspaceRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def load_optional(self, workspace_id: str) -> WorkspaceRecord | None:
        try:
            return self.load(workspace_id)
        except FileNotFoundError:
            return None

    def exists(self, workspace_id: str) -> bool:
        return self._record_path(workspace_id).is_file()

    def list(self, *, include_archived: bool = False) -> list[WorkspaceRecord]:
        records: list[WorkspaceRecord] = []
        for path in self.root.glob("*/workspace.json"):
            try:
                record = WorkspaceRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if include_archived or not record.archived:
                records.append(record)
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def update(
        self,
        workspace_id: str,
        *,
        title: str | None = None,
        mode: WorkspaceMode | None = None,
        archived: bool | None = None,
    ) -> WorkspaceRecord:
        record = self.load(workspace_id)
        if title is not None:
            normalized_title = str(title).strip()
            if not normalized_title:
                raise ValueError("workspace title must not be empty")
            record.title = normalized_title
        if mode is not None:
            record.mode = mode
        if archived is not None:
            record.archived = bool(archived)
        self.save(record)
        return record

    def save(self, record: WorkspaceRecord) -> None:
        record.updated_at = datetime.now(UTC).isoformat()
        path = self._record_path(record.workspace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def workdir(self, workspace_id: str) -> Path:
        record = self.load(workspace_id)
        path = Path(record.workdir_root).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def delete(self, workspace_id: str, *, delete_files: bool = True) -> WorkspaceRecord:
        record = self.load(workspace_id)
        workdir = Path(record.workdir_root).expanduser().resolve()
        if delete_files and record.root_kind == "managed" and workdir.exists():
            shutil.rmtree(workdir)
        record_path = self._record_path(record.workspace_id)
        record_path.unlink(missing_ok=True)
        parent = record_path.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
        return record

    def _record_path(self, workspace_id: str) -> Path:
        return self.root / _identifier(workspace_id) / "workspace.json"


def _identifier(value: str) -> str:
    identifier = str(value or "").strip()
    if not identifier or identifier in {".", ".."} or "/" in identifier or "\\" in identifier:
        raise ValueError(f"invalid workspace id: {value!r}")
    return identifier


def _workspace_root_path(
    value: Path | None,
    *,
    default: Path,
    require_existing: bool,
) -> Path:
    candidate = value.expanduser() if value is not None else default
    if not candidate.is_absolute():
        raise ValueError("workspace workdir_root must be an absolute path")
    resolved = candidate.resolve()
    if require_existing and not resolved.is_dir():
        raise FileNotFoundError(f"workspace directory not found: {resolved}")
    return resolved
