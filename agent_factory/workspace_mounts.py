from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import stat
import subprocess
from typing import Iterable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator


class WorkspaceMountRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mount_id: str
    name: str
    source_path: str
    created_at: str

    @field_validator("mount_id", "name", "source_path", "created_at")
    @classmethod
    def _required_text(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized


class WorkspaceMountService:
    def __init__(self, workdir_root: Path) -> None:
        self.workdir_root = workdir_root.expanduser().resolve()

    def mount(
        self,
        *,
        source_path: str,
        name: str | None,
        existing: Iterable[WorkspaceMountRecord],
    ) -> tuple[WorkspaceMountRecord, bool]:
        source = _existing_directory(source_path)
        if _path_is_within(source, self.workdir_root) or _path_is_within(self.workdir_root, source):
            raise ValueError("workspace mount directory must not contain or be contained by the session workdir")
        records = list(existing)
        for record in records:
            if Path(record.source_path).expanduser().resolve(strict=False) == source:
                return record, False

        mount_name = _mount_name(name or source.name)
        normalized_mount_name = _comparable_mount_name(mount_name)
        if any(_comparable_mount_name(record.name) == normalized_mount_name for record in records):
            raise ValueError(f"workspace mount name is already in use: {mount_name}")

        self.workdir_root.mkdir(parents=True, exist_ok=True)
        destination = self.workdir_root / mount_name
        if os.path.lexists(destination):
            raise ValueError(f"workspace entry is already in use: {mount_name}")

        _create_directory_link(source=source, destination=destination)
        return (
            WorkspaceMountRecord(
                mount_id=uuid4().hex,
                name=mount_name,
                source_path=str(source),
                created_at=datetime.now(UTC).isoformat(),
            ),
            True,
        )

    def unmount(self, record: WorkspaceMountRecord) -> None:
        destination = self.workdir_root / record.name
        if not os.path.lexists(destination):
            return
        _remove_directory_link(destination)

    def ensure_projection(self, record: WorkspaceMountRecord) -> bool:
        source = Path(record.source_path).expanduser().resolve(strict=False)
        destination = self.workdir_root / record.name
        if os.path.lexists(destination):
            return _link_matches(destination=destination, source=source)
        if not source.is_dir():
            return False
        _create_directory_link(source=source, destination=destination)
        return True


def workspace_mount_payload(record: WorkspaceMountRecord, *, workdir_root: Path) -> dict[str, object]:
    source = Path(record.source_path).expanduser().resolve(strict=False)
    destination = workdir_root.expanduser().resolve() / record.name
    return {
        **record.model_dump(mode="json"),
        "connected": source.is_dir() and _link_matches(destination=destination, source=source),
    }


def _mount_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("workspace mount name must not be empty")
    if name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("workspace mount name must be a single directory name")
    return name


def _comparable_mount_name(value: str) -> str:
    return value.casefold() if os.name == "nt" else value


def _existing_directory(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("source_path must not be empty")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("source_path must be an absolute path")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"workspace mount directory not found: {resolved}")
    return resolved


def _create_directory_link(*, source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "& { param([string]$LinkPath, [string]$TargetPath) "
                "$ErrorActionPreference='Stop'; "
                "New-Item -ItemType Junction -Path $LinkPath -Target $TargetPath | Out-Null }",
                str(destination),
                str(source),
            ],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise OSError(detail or f"failed to create workspace junction: {destination}")
        return
    destination.symlink_to(source, target_is_directory=True)


def _remove_directory_link(destination: Path) -> None:
    if os.name == "nt":
        attributes = getattr(os.lstat(destination), "st_file_attributes", 0)
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if not reparse_point or not attributes & reparse_point:
            raise ValueError(f"workspace mount projection is not a directory junction: {destination}")
        os.rmdir(destination)
        return
    if not destination.is_symlink():
        raise ValueError(f"workspace mount projection is not a symbolic link: {destination}")
    destination.unlink()


def _link_matches(*, destination: Path, source: Path) -> bool:
    if not os.path.lexists(destination):
        return False
    try:
        return destination.resolve(strict=False) == source.resolve(strict=False)
    except OSError:
        return False


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
