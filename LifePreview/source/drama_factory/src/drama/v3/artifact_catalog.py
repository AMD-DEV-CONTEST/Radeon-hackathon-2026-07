from __future__ import annotations

import hashlib
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shared_contracts import ArtifactRef, ComponentName, stable_json_sha256

from ..runtime import ProjectLock, atomic_write_json


class FactoryArtifactError(RuntimeError):
    pass


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactoryArtifactLocator(_FrozenModel):
    artifact: ArtifactRef
    relative_path: str = Field(min_length=1, max_length=1000)
    role: str = Field(min_length=1, max_length=100)
    created_at: datetime


class FactoryArtifactCatalogSnapshot(_FrozenModel):
    schema_version: Literal["factory.artifact-catalog.v1"] = (
        "factory.artifact-catalog.v1"
    )
    artifacts: tuple[FactoryArtifactLocator, ...]
    updated_at: datetime
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_catalog(self):
        ids = [item.artifact.artifact_id for item in self.artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("factory artifact ids must be unique")
        paths = [item.relative_path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("factory artifact paths must be unique")
        identity = self.model_dump(mode="json", exclude={"catalog_sha256"})
        if self.catalog_sha256 != stable_json_sha256(identity):
            raise ValueError("factory artifact catalog hash does not match")
        return self


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _snapshot(
    artifacts: tuple[FactoryArtifactLocator, ...],
    *,
    updated_at: datetime | None = None,
) -> FactoryArtifactCatalogSnapshot:
    now = updated_at or datetime.now(timezone.utc)
    draft = FactoryArtifactCatalogSnapshot.model_construct(
        schema_version="factory.artifact-catalog.v1",
        artifacts=artifacts,
        updated_at=now,
        catalog_sha256="0" * 64,
    )
    identity = draft.model_dump(mode="json", exclude={"catalog_sha256"})
    return FactoryArtifactCatalogSnapshot(
        schema_version="factory.artifact-catalog.v1",
        artifacts=artifacts,
        updated_at=now,
        catalog_sha256=stable_json_sha256(identity),
    )


def _image_mime_from_header(header: bytes) -> str:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    raise FactoryArtifactError("unsupported or malformed image artifact")


def _image_mime(path: Path) -> str:
    return _image_mime_from_header(path.read_bytes()[:16])


class FactoryArtifactCatalog:
    """Private project-local locator map; locators never cross the Hub API."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / "factory_v3"
        self.artifacts_root = self.root / "artifacts"
        self.path = self.root / "artifact_catalog.json"

    def load(self) -> FactoryArtifactCatalogSnapshot:
        if not self.path.is_file():
            return _snapshot(())
        return FactoryArtifactCatalogSnapshot.model_validate_json(
            self.path.read_text(encoding="utf-8")
        )

    def _write(self, snapshot: FactoryArtifactCatalogSnapshot) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, snapshot.model_dump(mode="json"))

    def import_image(
        self,
        source: str | Path,
        *,
        role: str,
        artifact_id: UUID | None = None,
    ) -> ArtifactRef:
        path = Path(source).resolve()
        if not path.is_file():
            raise FactoryArtifactError("image artifact is unavailable")
        mime = _image_mime(path)
        sha256, size = _hash_file(path)
        artifact = ArtifactRef(
            owner=ComponentName.DRAMA_FACTORY,
            artifact_id=artifact_id or uuid4(),
            sha256=sha256,
            bytes=size,
            mime=mime,
            version=1,
        )
        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }[mime]
        destination = (
            self.artifacts_root
            / "inputs"
            / f"{artifact.artifact_id}{suffix}"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        shutil.copyfile(path, temporary)
        temporary.replace(destination)
        self.bind(artifact, destination, role=role)
        return artifact

    def import_image_bytes(
        self,
        content: bytes,
        *,
        role: str,
        artifact_id: UUID | None = None,
        maximum_bytes: int = 20 * 1024 * 1024,
    ) -> ArtifactRef:
        if not content or len(content) > maximum_bytes:
            raise FactoryArtifactError("image upload size is invalid")
        mime = _image_mime_from_header(content[:16])
        artifact = ArtifactRef(
            owner=ComponentName.DRAMA_FACTORY,
            artifact_id=artifact_id or uuid4(),
            sha256=hashlib.sha256(content).hexdigest(),
            bytes=len(content),
            mime=mime,
            version=1,
        )
        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }[mime]
        destination = (
            self.artifacts_root
            / "inputs"
            / f"{artifact.artifact_id}{suffix}"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        temporary.write_bytes(content)
        temporary.replace(destination)
        self.bind(artifact, destination, role=role)
        return artifact

    def bind(
        self,
        artifact: ArtifactRef,
        path: str | Path,
        *,
        role: str,
        created_at: datetime | None = None,
    ) -> FactoryArtifactCatalogSnapshot:
        source = Path(path).resolve()
        try:
            relative = source.relative_to(self.project_root)
        except ValueError as exc:
            raise FactoryArtifactError(
                "factory artifact must remain inside its project"
            ) from exc
        if artifact.owner is not ComponentName.DRAMA_FACTORY:
            raise FactoryArtifactError("factory cannot bind a foreign artifact")
        if not source.is_file():
            raise FactoryArtifactError("factory artifact is unavailable")
        sha256, size = _hash_file(source)
        if sha256 != artifact.sha256 or size != artifact.bytes:
            raise FactoryArtifactError("factory artifact identity does not match")
        normalized = relative.as_posix()

        with ProjectLock(self.project_root):
            snapshot = self.load()
            existing = next(
                (
                    item
                    for item in snapshot.artifacts
                    if item.artifact.artifact_id == artifact.artifact_id
                ),
                None,
            )
            locator = FactoryArtifactLocator(
                artifact=artifact,
                relative_path=normalized,
                role=role,
                created_at=created_at or datetime.now(timezone.utc),
            )
            if existing is not None:
                if existing != locator and (
                    existing.artifact != locator.artifact
                    or existing.relative_path != locator.relative_path
                    or existing.role != locator.role
                ):
                    raise FactoryArtifactError(
                        "factory artifact binding conflicts with catalog"
                    )
                return snapshot
            updated = _snapshot(
                (*snapshot.artifacts, locator),
                updated_at=created_at,
            )
            self._write(updated)
            return updated

    def resolve(self, artifact: ArtifactRef) -> Path:
        snapshot = self.load()
        locator = next(
            (
                item
                for item in snapshot.artifacts
                if item.artifact.artifact_id == artifact.artifact_id
            ),
            None,
        )
        if locator is None or locator.artifact != artifact:
            raise FactoryArtifactError("factory artifact is not registered")
        path = (self.project_root / locator.relative_path).resolve()
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise FactoryArtifactError(
                "factory artifact locator escapes project"
            ) from exc
        if not path.is_file():
            raise FactoryArtifactError("factory artifact file is unavailable")
        sha256, size = _hash_file(path)
        if sha256 != artifact.sha256 or size != artifact.bytes:
            raise FactoryArtifactError("factory artifact changed after binding")
        detected, _ = mimetypes.guess_type(path.name)
        if detected and artifact.mime.startswith("image/") and not detected.startswith(
            "image/"
        ):
            raise FactoryArtifactError("factory artifact extension is inconsistent")
        return path
