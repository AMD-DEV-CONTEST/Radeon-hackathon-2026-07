from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import ConfigDict
from sqlalchemy.orm import sessionmaker
from sqlmodel import Field, Session, SQLModel

from ..exceptions import NotFoundError, ValidationError
from ..observability import record_counter, start_span
from .storage.models import ArtifactKind, ArtifactRow
from .storage.repositories import ArtifactRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RegisterArtifactInput(SQLModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    absolute_path: str
    kind: ArtifactKind = ArtifactKind.OTHER
    mime_type: str | None = None
    summary: str | None = None
    preview_payload: dict[str, Any] | None = Field(default=None)
    metadata_payload: dict[str, Any] = Field(default_factory=dict)
    ready_to_open: bool = True


class ResolvedArtifact(SQLModel):
    artifact_id: str
    title: str
    kind: ArtifactKind
    absolute_path: str
    exists: bool
    ready_to_open: bool
    mime_type: str | None = None
    summary: str | None = None
    preview_payload: dict[str, Any] | None = None
    metadata_payload: dict[str, Any] = Field(default_factory=dict)
    view: str | None = None


class ActivatedArtifact(SQLModel):
    artifact_id: str
    title: str
    absolute_path: str
    opened: bool


def _open_file_with_os(path: Path) -> bool:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return True
    if sys.platform == "darwin":
        return subprocess.run(["open", str(path)], check=False).returncode == 0
    return subprocess.run(["xdg-open", str(path)], check=False).returncode == 0


def build_artifact_uri(artifact_id: str, *, view: str | None = None) -> str:
    artifact_id = artifact_id.strip()
    if not artifact_id:
        raise ValidationError("Artifact id cannot be empty.")

    query = urlencode({"view": view}) if view else ""
    return urlunparse(("artifact", artifact_id, "", "", query, ""))


def build_artifact_markdown_link(row: ArtifactRow, *, label: str | None = None, view: str | None = None) -> str:
    link_label = (label or row.title).strip() or row.id
    return f"[{link_label}]({build_artifact_uri(row.id, view=view)})"


class ArtifactService:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._artifacts = ArtifactRepository()

    def register_artifact(self, input_data: RegisterArtifactInput) -> ArtifactRow:
        attributes = {"artifact.kind": input_data.kind.value}
        with start_span("artifact.register", attributes):
            with self._session_factory() as session:
                row = self.register_artifact_in_session(session, input_data)
                session.commit()
                record_counter("xenix.artifact.register.count", attributes={**attributes, "status": "succeeded"})
                return row

    def register_artifact_in_session(
        self,
        session: Session,
        input_data: RegisterArtifactInput,
    ) -> ArtifactRow:
        """Register through a caller-owned transaction.

        Import admission uses this seam so the app-owned source Artifact and its
        durable queued attempt become visible together.
        """

        title = input_data.title.strip()
        if not title:
            raise ValidationError("Artifact title cannot be empty.")
        path = Path(input_data.absolute_path).expanduser()
        if not path.is_absolute():
            raise ValidationError("Artifact path must be absolute.")
        if not path.exists():
            raise ValidationError("Artifact path must exist.")
        row = ArtifactRow(
            kind=input_data.kind,
            title=title,
            absolute_path=str(path),
            mime_type=input_data.mime_type,
            summary=input_data.summary,
            preview_payload=input_data.preview_payload,
            metadata_payload=dict(input_data.metadata_payload),
            ready_to_open=input_data.ready_to_open,
            created_at=_utc_now(),
        )
        return self._artifacts.create(session, row)

    def unregister_artifact_in_session(
        self,
        session: Session,
        artifact_id: str,
    ) -> bool:
        """Remove one registration inside an owner-coordinated transaction.

        This does not delete bytes. The calling content owner must first remove all
        durable references and separately reclaim only storage that it owns.
        """

        return self._artifacts.delete(session, artifact_id)

    def resolve_uri(self, uri: str) -> ResolvedArtifact:
        parsed = urlparse(uri)
        if parsed.scheme != "artifact":
            raise ValidationError("Artifact URI must use the artifact scheme.")

        artifact_id = parsed.netloc or parsed.path.lstrip("/").split("/", 1)[0]
        artifact_id = artifact_id.strip()
        if not artifact_id:
            raise ValidationError("Artifact URI is missing an artifact id.")
        view = parse_qs(parsed.query).get("view", [None])[0]

        with self._session_factory() as session:
            row = self._artifacts.get(session, artifact_id)
            if row is None:
                raise NotFoundError(f"Artifact '{artifact_id}' was not found.")
            path = Path(row.absolute_path)
            return ResolvedArtifact(
                artifact_id=row.id,
                title=row.title,
                kind=row.kind,
                absolute_path=row.absolute_path,
                exists=path.exists(),
                ready_to_open=row.ready_to_open,
                mime_type=row.mime_type,
                summary=row.summary,
                preview_payload=row.preview_payload,
                metadata_payload=dict(row.metadata_payload),
                view=view,
            )

    def activate_uri(self, uri: str) -> ActivatedArtifact:
        artifact = self.resolve_uri(uri)
        if not artifact.ready_to_open:
            raise ValidationError("Artifact is not ready to open.")
        if not artifact.exists:
            raise NotFoundError(f"Artifact file is missing: {artifact.absolute_path}")
        try:
            opened = _open_file_with_os(Path(artifact.absolute_path))
        except OSError as exc:
            raise ValidationError(f"Could not open artifact: {artifact.absolute_path}") from exc
        if not opened:
            raise ValidationError(f"Could not open artifact: {artifact.absolute_path}")
        return ActivatedArtifact(
            artifact_id=artifact.artifact_id,
            title=artifact.title,
            absolute_path=artifact.absolute_path,
            opened=True,
        )
