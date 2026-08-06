"""Constrained filesystem effects for E7-managed export artifacts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import ClassVar, Protocol
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import ExportFormat


class ArtifactStoreError(OSError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ArtifactStore(Protocol):
    def path_for(
        self,
        *,
        asset_id: UUID,
        draft_id: UUID,
        request_id: UUID,
        format: ExportFormat,
    ) -> str: ...

    def write(self, path: str, data: bytes) -> None: ...

    def delete(self, path: str) -> None: ...

    def exists(self, path: str) -> bool: ...

    def read(self, path: str) -> bytes: ...


class LocalArtifactStore:
    """Writes only below one configured root and verifies idempotent replays."""

    _EXTENSIONS: ClassVar[dict[ExportFormat, str]] = {
        ExportFormat.HTML: "html",
        ExportFormat.MARKDOWN: "md",
        ExportFormat.JSON: "json",
    }

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str | Path) -> Path:
        candidate = Path(path).resolve(strict=False)
        if candidate != self.root and self.root not in candidate.parents:
            raise ArtifactStoreError("PATH_OUTSIDE_EXPORT_ROOT", "Export path escapes its root.")
        return candidate

    def path_for(
        self,
        *,
        asset_id: UUID,
        draft_id: UUID,
        request_id: UUID,
        format: ExportFormat,
    ) -> str:
        extension = self._EXTENSIONS[format]
        return str(
            self._resolve(
                self.root
                / str(asset_id)
                / str(draft_id)
                / str(request_id)
                / f"delivery.{extension}"
            )
        )

    def write(self, path: str, data: bytes) -> None:
        destination = self._resolve(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_file() and destination.read_bytes() == data:
                return
            raise ArtifactStoreError(
                "EXISTING_FILE_HASH_MISMATCH",
                "An existing managed export differs from the deterministic bytes.",
            )
        temporary = destination.with_name(f".{destination.name}.tmp-{uuid4()}")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ArtifactStoreError(
                "FILESYSTEM_WRITE_FAILED", "Could not write export file."
            ) from exc

    def delete(self, path: str) -> None:
        destination = self._resolve(path)
        try:
            destination.unlink(missing_ok=True)
        except OSError as exc:
            raise ArtifactStoreError(
                "FILESYSTEM_DELETE_FAILED", "Could not delete export file."
            ) from exc

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def read(self, path: str) -> bytes:
        try:
            return self._resolve(path).read_bytes()
        except OSError as exc:
            raise ArtifactStoreError(
                "FILESYSTEM_READ_FAILED", "Could not read export file."
            ) from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
