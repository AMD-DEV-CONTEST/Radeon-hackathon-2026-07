from __future__ import annotations

import webbrowser
from urllib.parse import urlparse

from sqlmodel import SQLModel

from ..exceptions import ValidationError
from .artifact_service import ArtifactService


class LinkActivationResult(SQLModel):
    uri: str
    scheme: str
    opened: bool
    artifact_id: str | None = None


class LinkRouter:
    def __init__(
        self,
        *,
        artifact_service: ArtifactService,
    ) -> None:
        self._artifact_service = artifact_service

    def activate(self, uri: str, *, thread_id: str | None = None) -> LinkActivationResult:
        _ = thread_id
        parsed = urlparse(uri)
        scheme = parsed.scheme
        if scheme == "artifact":
            artifact = self._artifact_service.activate_uri(uri)
            return LinkActivationResult(
                uri=uri,
                scheme=scheme,
                opened=artifact.opened,
                artifact_id=artifact.artifact_id,
            )
        if scheme == "dataset":
            raise ValidationError("Dataset URI scheme is not supported.")
        if not uri.strip():
            raise ValidationError("Link URI cannot be empty.")
        opened = webbrowser.open(uri)
        if not opened:
            raise ValidationError(f"Could not open link: {uri}")
        return LinkActivationResult(uri=uri, scheme=scheme, opened=True)
