from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from drama.v3.audio_pipeline import (
    AcceptedAudioArtifact,
    FinalAudioTrack,
    SilencePolicyRevision,
)

from creative_hub.db.canonical import canonical_json_digest


_AUTHORITY_SCHEMA = "shidu-audio-authority-bundle.v1"
_FINAL_AUDIO_ROLES = ("ambience", "sfx", "music")
_MAX_AUTHORITY_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class FrozenAudioAuthorityResolver:
    project_id: UUID
    tracks: tuple[FinalAudioTrack, ...]

    def resolve_accepted_audio(
        self,
        *,
        project_id: UUID,
        role: str,
        declared: AcceptedAudioArtifact,
    ) -> AcceptedAudioArtifact | None:
        track = self._track(project_id, role)
        if track is None or track.artifact != declared:
            return None
        return declared

    def resolve_silence_policy(
        self,
        *,
        project_id: UUID,
        role: str,
        declared: SilencePolicyRevision,
    ) -> SilencePolicyRevision | None:
        track = self._track(project_id, role)
        if track is None or track.silence_policy != declared:
            return None
        return declared

    def _track(self, project_id: UUID, role: str) -> FinalAudioTrack | None:
        if project_id != self.project_id:
            return None
        return next((item for item in self.tracks if item.role == role), None)


def load_frozen_audio_authority_resolver(
    path: Path | str,
    *,
    expected_project_id: UUID,
) -> FrozenAudioAuthorityResolver:
    location = Path(path)
    try:
        if (
            location.is_symlink()
            or not location.is_file()
            or location.stat().st_size > _MAX_AUTHORITY_BYTES
        ):
            raise OSError
        raw = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("audio authority file is unreadable") from None
    if not isinstance(raw, dict) or raw.get("schema_version") != _AUTHORITY_SCHEMA:
        raise ValueError("audio authority schema is invalid")
    material = dict(raw)
    digest = material.pop("digest", None)
    if digest != canonical_json_digest(material):
        raise ValueError("audio authority digest does not match content")
    try:
        project_id = UUID(str(raw["project_id"]))
        tracks = tuple(
            FinalAudioTrack.model_validate(item)
            for item in raw["final_audio_tracks"]
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError("audio authority content is invalid") from None
    if project_id != expected_project_id:
        raise ValueError("audio authority project does not match deployment")
    if tuple(item.role for item in tracks) != _FINAL_AUDIO_ROLES:
        raise ValueError("audio authority track roles are invalid")
    return FrozenAudioAuthorityResolver(project_id=project_id, tracks=tracks)


__all__ = [
    "FrozenAudioAuthorityResolver",
    "load_frozen_audio_authority_resolver",
]
