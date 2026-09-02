"""Fail-closed assembly of selected native-audio H3 video segments."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from shared_contracts import H3AttemptSelectionV1, H3SourceLineageV1


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_QC_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SCHEMA_VERSION = "h3.assembly.v1"
_VIDEO_CODEC = "h264"
_AUDIO_CODEC = "aac"
_WIDTH = 1344
_HEIGHT = 768
_FPS = 24.0
_DURATION_TOLERANCE_SECONDS = 1.0 / _FPS
_PERSISTED_AUTHORITY_SCHEMA = "h3.persisted-selection-authority.v1"


class H3AssemblyError(RuntimeError):
    """The selected H3 artifacts cannot safely become a final delivery."""


def _require_digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise H3AssemblyError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise H3AssemblyError(f"{label} must be a positive integer")
    return value


def _require_finite_positive_number(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise H3AssemblyError(f"{label} must be a finite positive number")
    return float(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise H3AssemblyError("artifact cannot be read for digest verification") from exc
    return digest.hexdigest()


def _canonical_digest(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise H3AssemblyError("assembly manifest is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class H3MediaProfile:
    """The stream facts reported by the injected media probe."""

    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    duration_seconds: float
    stream_types: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_positive_int(self.width, "media width")
        _require_positive_int(self.height, "media height")
        _require_finite_positive_number(self.fps, "media fps")
        _require_finite_positive_number(self.duration_seconds, "media duration")
        if type(self.video_codec) is not str or not self.video_codec:
            raise H3AssemblyError("media video codec must be a non-empty string")
        if type(self.audio_codec) is not str or not self.audio_codec:
            raise H3AssemblyError("media audio codec must be a non-empty string")
        if type(self.stream_types) is not tuple or not all(
            type(stream_type) is str and stream_type for stream_type in self.stream_types
        ):
            raise H3AssemblyError("media stream types must be a tuple of non-empty strings")


@dataclass(frozen=True, slots=True)
class H3SelectedSegment:
    """One sealed selection aggregate loaded from durable persistence."""

    schema_version: str
    ordinal: int
    sequence_id: UUID
    sequence_revision_id: UUID
    selected_attempt_id: UUID
    artifact_id: UUID
    sequence_plan_digest: str
    selection_revision_id: UUID
    selection_payload_digest: str
    source_lineage_digest: str
    qc_evaluation_id: UUID
    qc_evaluation_digest: str
    selection: H3AttemptSelectionV1
    source_lineage: H3SourceLineageV1
    authority_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != _PERSISTED_AUTHORITY_SCHEMA:
            raise H3AssemblyError("persisted selection authority schema is not pinned")
        _require_positive_int(self.ordinal, "segment ordinal")
        if type(self.sequence_id) is not UUID:
            raise H3AssemblyError("sequence id must be a UUID")
        if type(self.sequence_revision_id) is not UUID:
            raise H3AssemblyError("sequence revision id must be a UUID")
        if type(self.selected_attempt_id) is not UUID:
            raise H3AssemblyError("selected attempt id must be a UUID")
        if type(self.artifact_id) is not UUID:
            raise H3AssemblyError("selected artifact id must be a UUID")
        if type(self.selection_revision_id) is not UUID:
            raise H3AssemblyError("selection revision id must be a UUID")
        if type(self.qc_evaluation_id) is not UUID:
            raise H3AssemblyError("QC evaluation id must be a UUID")
        _require_digest(self.sequence_plan_digest, "sequence plan digest")
        _require_digest(self.selection_payload_digest, "selection payload digest")
        _require_digest(self.source_lineage_digest, "source lineage digest")
        _require_digest(self.qc_evaluation_digest, "QC evaluation digest")
        try:
            selection = H3AttemptSelectionV1.model_validate(self.selection)
            lineage = H3SourceLineageV1.model_validate(self.source_lineage)
        except ValidationError as exc:
            raise H3AssemblyError("selected segment authority is invalid") from exc
        if selection.sequence_id != self.sequence_id:
            raise H3AssemblyError("selection sequence does not match selected segment")
        if lineage.attempt_ordinal != selection.selected_attempt_ordinal:
            raise H3AssemblyError("source lineage does not match selected attempt ordinal")
        if lineage.attempt_ordinal == 0 and lineage.repair_trigger_codes:
            raise H3AssemblyError("initial source lineage cannot carry repair triggers")
        if lineage.attempt_ordinal == 1 and not lineage.repair_trigger_codes:
            raise H3AssemblyError("repair source lineage requires trigger codes")
        _require_digest(lineage.artifact_digest, "segment artifact digest")
        if any(not _QC_CODE_RE.fullmatch(code) for code in selection.exception_codes):
            raise H3AssemblyError("QC exception codes must be safe lowercase identifiers")
        if self.selection_payload_digest != _canonical_digest(
            selection.model_dump(mode="json")
        ):
            raise H3AssemblyError("persisted selection payload digest mismatch")
        if self.source_lineage_digest != _canonical_digest(
            lineage.model_dump(mode="json")
        ):
            raise H3AssemblyError("persisted source lineage digest mismatch")
        _require_digest(self.authority_digest, "selected segment authority digest")
        expected_authority_digest = _canonical_digest(
            _selected_segment_authority_payload(
                schema_version=self.schema_version,
                ordinal=self.ordinal,
                sequence_id=self.sequence_id,
                sequence_revision_id=self.sequence_revision_id,
                selected_attempt_id=self.selected_attempt_id,
                artifact_id=self.artifact_id,
                sequence_plan_digest=self.sequence_plan_digest,
                selection_revision_id=self.selection_revision_id,
                selection_payload_digest=self.selection_payload_digest,
                source_lineage_digest=self.source_lineage_digest,
                qc_evaluation_id=self.qc_evaluation_id,
                qc_evaluation_digest=self.qc_evaluation_digest,
                selection=selection,
                source_lineage=lineage,
            )
        )
        if self.authority_digest != expected_authority_digest:
            raise H3AssemblyError("selected segment authority digest mismatch")
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "source_lineage", lineage)

    @property
    def artifact_digest(self) -> str:
        return self.source_lineage.artifact_digest

    @property
    def qc_exception_codes(self) -> tuple[str, ...]:
        return self.selection.exception_codes

    @property
    def selected_attempt_ordinal(self) -> int:
        return self.selection.selected_attempt_ordinal


def _selected_segment_authority_payload(
    *,
    schema_version: str,
    ordinal: int,
    sequence_id: UUID,
    sequence_revision_id: UUID,
    selected_attempt_id: UUID,
    artifact_id: UUID,
    sequence_plan_digest: str,
    selection_revision_id: UUID,
    selection_payload_digest: str,
    source_lineage_digest: str,
    qc_evaluation_id: UUID,
    qc_evaluation_digest: str,
    selection: H3AttemptSelectionV1,
    source_lineage: H3SourceLineageV1,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "ordinal": ordinal,
        "sequence_id": str(sequence_id),
        "sequence_revision_id": str(sequence_revision_id),
        "selected_attempt_id": str(selected_attempt_id),
        "artifact_id": str(artifact_id),
        "sequence_plan_digest": sequence_plan_digest,
        "selection_revision_id": str(selection_revision_id),
        "selection_payload_digest": selection_payload_digest,
        "source_lineage_digest": source_lineage_digest,
        "qc_evaluation_id": str(qc_evaluation_id),
        "qc_evaluation_digest": qc_evaluation_digest,
        "selection": selection.model_dump(mode="json"),
        "source_lineage": source_lineage.model_dump(mode="json"),
    }


def _manifest_payload(
    *,
    schema_version: str,
    episode_revision_id: UUID,
    segments: tuple[H3SelectedSegment, ...],
    segment_duration_seconds: tuple[float, ...],
    final_duration_seconds: float,
    output_artifact_digest: str,
    qc_exception_segments: tuple[int, ...],
    width: int,
    height: int,
    fps: float,
    video_codec: str,
    audio_codec: str,
    subtitles: bool,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "episode_revision_id": str(episode_revision_id),
        "segments": [
            {
                "authority_schema_version": segment.schema_version,
                "ordinal": segment.ordinal,
                "sequence_id": str(segment.sequence_id),
                "sequence_revision_id": str(segment.sequence_revision_id),
                "selected_attempt_id": str(segment.selected_attempt_id),
                "artifact_id": str(segment.artifact_id),
                "artifact_digest": segment.artifact_digest,
                "qc_exception_codes": list(segment.qc_exception_codes),
                "selected_attempt_ordinal": segment.selected_attempt_ordinal,
                "sequence_plan_digest": segment.sequence_plan_digest,
                "selection_revision_id": str(segment.selection_revision_id),
                "selection_payload_digest": segment.selection_payload_digest,
                "source_lineage_digest": segment.source_lineage_digest,
                "qc_evaluation_id": str(segment.qc_evaluation_id),
                "qc_evaluation_digest": segment.qc_evaluation_digest,
                "selection": segment.selection.model_dump(mode="json"),
                "source_lineage": segment.source_lineage.model_dump(mode="json"),
                "authority_digest": segment.authority_digest,
            }
            for segment in segments
        ],
        "segment_duration_seconds": list(segment_duration_seconds),
        "final_duration_seconds": final_duration_seconds,
        "output_artifact_digest": output_artifact_digest,
        "qc_exception_segments": list(qc_exception_segments),
        "width": width,
        "height": height,
        "fps": fps,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "subtitles": subtitles,
    }


@dataclass(frozen=True, slots=True)
class H3AssemblyManifest:
    """A digest-bound, subtitle-free record of a final H3 assembly."""

    schema_version: str
    episode_revision_id: UUID
    segments: tuple[H3SelectedSegment, ...]
    segment_duration_seconds: tuple[float, ...]
    final_duration_seconds: float
    output_artifact_digest: str
    qc_exception_segments: tuple[int, ...]
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    subtitles: bool
    manifest_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise H3AssemblyError("assembly manifest schema version is not pinned")
        if type(self.episode_revision_id) is not UUID:
            raise H3AssemblyError("episode revision id must be a UUID")
        if type(self.segments) is not tuple or not self.segments or any(
            type(segment) is not H3SelectedSegment for segment in self.segments
        ):
            raise H3AssemblyError("assembly manifest segments are invalid")
        _validate_segment_sequence(self.segments)
        if (
            type(self.segment_duration_seconds) is not tuple
            or len(self.segment_duration_seconds) != len(self.segments)
        ):
            raise H3AssemblyError("segment durations must align with selected segments")
        normalized_durations = tuple(
            _require_finite_positive_number(duration, "segment duration")
            for duration in self.segment_duration_seconds
        )
        if normalized_durations != self.segment_duration_seconds:
            raise H3AssemblyError("segment durations must use canonical floats")
        final_duration = _require_finite_positive_number(
            self.final_duration_seconds, "final duration"
        )
        if not math.isclose(
            final_duration,
            math.fsum(normalized_durations),
            rel_tol=0.0,
            abs_tol=_DURATION_TOLERANCE_SECONDS,
        ):
            raise H3AssemblyError("final duration does not match selected segments")
        _require_digest(self.output_artifact_digest, "final artifact digest")
        if type(self.qc_exception_segments) is not tuple or any(
            type(ordinal) is not int for ordinal in self.qc_exception_segments
        ):
            raise H3AssemblyError("QC exception segment ordinals are invalid")
        expected_exceptions = tuple(
            segment.ordinal for segment in self.segments if segment.qc_exception_codes
        )
        if self.qc_exception_segments != expected_exceptions:
            raise H3AssemblyError("QC exception segments do not match selected segments")
        _validate_canonical_profile_fields(
            width=self.width,
            height=self.height,
            fps=self.fps,
            video_codec=self.video_codec,
            audio_codec=self.audio_codec,
            subtitles=self.subtitles,
        )
        _require_digest(self.manifest_digest, "assembly manifest digest")
        if self.manifest_digest != self.recompute_digest():
            raise H3AssemblyError("assembly manifest digest does not match its payload")

    def recompute_digest(self) -> str:
        """Return the SHA-256 digest over every manifest field except itself."""

        return _canonical_digest(
            _manifest_payload(
                schema_version=self.schema_version,
                episode_revision_id=self.episode_revision_id,
                segments=self.segments,
                segment_duration_seconds=self.segment_duration_seconds,
                final_duration_seconds=self.final_duration_seconds,
                output_artifact_digest=self.output_artifact_digest,
                qc_exception_segments=self.qc_exception_segments,
                width=self.width,
                height=self.height,
                fps=self.fps,
                video_codec=self.video_codec,
                audio_codec=self.audio_codec,
                subtitles=self.subtitles,
            )
        )


class H3MediaProbeBackend(Protocol):
    def probe(self, path: Path) -> H3MediaProfile: ...


class H3ConcatRunner(Protocol):
    def concat(self, inputs: tuple[Path, ...], destination: Path) -> None: ...


H3PersistedSelectionAuthorityResolver = Callable[
    [UUID], tuple[H3SelectedSegment, ...]
]
H3ArtifactResolver = Callable[[UUID], Path]


def _validate_segment_sequence(segments: tuple[H3SelectedSegment, ...]) -> None:
    expected_ordinals = tuple(range(1, len(segments) + 1))
    actual_ordinals = tuple(segment.ordinal for segment in segments)
    if actual_ordinals != expected_ordinals:
        raise H3AssemblyError("segment ordinal sequence must be contiguous from one")
    attempt_ids = tuple(segment.selected_attempt_id for segment in segments)
    if len(set(attempt_ids)) != len(attempt_ids):
        raise H3AssemblyError("selected attempt ids must not be reused")
    sequence_ids = tuple(segment.sequence_id for segment in segments)
    if len(set(sequence_ids)) != len(sequence_ids):
        raise H3AssemblyError("sequence ids must not be reused")
    sequence_revision_ids = tuple(
        segment.sequence_revision_id for segment in segments
    )
    if len(set(sequence_revision_ids)) != len(sequence_revision_ids):
        raise H3AssemblyError("sequence revision ids must not be reused")


def _validate_canonical_profile_fields(
    *,
    width: object,
    height: object,
    fps: object,
    video_codec: object,
    audio_codec: object,
    subtitles: object,
) -> None:
    if (
        type(width) is not int
        or type(height) is not int
        or type(fps) not in (int, float)
        or not math.isfinite(fps)
        or type(video_codec) is not str
        or type(audio_codec) is not str
        or type(subtitles) is not bool
        or width != _WIDTH
        or height != _HEIGHT
        or float(fps) != _FPS
        or video_codec.casefold() != _VIDEO_CODEC
        or audio_codec.casefold() != _AUDIO_CODEC
        or subtitles is not False
    ):
        raise H3AssemblyError("media profile does not match the pinned H3 assembly profile")


def _validate_profile(profile: H3MediaProfile) -> None:
    if type(profile) is not H3MediaProfile:
        raise H3AssemblyError("media probe returned an invalid profile")
    _validate_canonical_profile_fields(
        width=profile.width,
        height=profile.height,
        fps=profile.fps,
        video_codec=profile.video_codec,
        audio_codec=profile.audio_codec,
        subtitles=False,
    )
    stream_types = profile.stream_types
    if (
        len(stream_types) != 2
        or stream_types.count("video") != 1
        or stream_types.count("audio") != 1
    ):
        raise H3AssemblyError("media profile must contain exactly one video and one audio stream")


def _validate_source_path(path: object) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.suffix.casefold() != ".mp4":
        raise H3AssemblyError("resolved artifact path is unsafe")
    try:
        if path.is_symlink() or not path.is_file():
            raise H3AssemblyError("resolved artifact path is not a regular file")
        path.resolve(strict=True)
    except H3AssemblyError:
        raise
    except OSError as exc:
        raise H3AssemblyError("resolved artifact path cannot be inspected") from exc
    return path


def _validate_destination_path(path: object) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.suffix.casefold() != ".mp4":
        raise H3AssemblyError("assembly destination path is unsafe")
    try:
        if not path.parent.is_dir() or path.is_symlink() or path.exists():
            raise H3AssemblyError("assembly destination must be a new regular MP4 path")
        path.parent.resolve(strict=True)
    except H3AssemblyError:
        raise
    except OSError as exc:
        raise H3AssemblyError("assembly destination path cannot be inspected") from exc
    return path


@dataclass(frozen=True, slots=True)
class _VerifiedSource:
    path: Path
    digest: str
    size: int
    mtime_ns: int


def _verify_source(path: Path, expected_digest: str) -> _VerifiedSource:
    try:
        initial_stat = path.stat()
    except OSError as exc:
        raise H3AssemblyError("resolved artifact cannot be inspected") from exc
    if initial_stat.st_size <= 0:
        raise H3AssemblyError("resolved artifact must not be empty")
    actual_digest = _sha256_file(path)
    try:
        final_stat = path.stat()
    except OSError as exc:
        raise H3AssemblyError("resolved artifact changed during digest verification") from exc
    if (
        final_stat.st_size != initial_stat.st_size
        or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
        or actual_digest != expected_digest
    ):
        raise H3AssemblyError("resolved artifact digest does not match selected authority")
    return _VerifiedSource(
        path=path,
        digest=actual_digest,
        size=initial_stat.st_size,
        mtime_ns=initial_stat.st_mtime_ns,
    )


def _ensure_source_unchanged(source: _VerifiedSource) -> None:
    try:
        current_stat = source.path.stat()
    except OSError as exc:
        raise H3AssemblyError("resolved artifact changed before concat") from exc
    if (
        current_stat.st_size != source.size
        or current_stat.st_mtime_ns != source.mtime_ns
        or _sha256_file(source.path) != source.digest
    ):
        raise H3AssemblyError("resolved artifact changed before concat")


class H3AssemblyAdapter:
    """Inject media inspection and concat execution behind an immutable authority."""

    def __init__(self, *, probe: H3MediaProbeBackend, concat_runner: H3ConcatRunner) -> None:
        if not callable(getattr(probe, "probe", None)):
            raise H3AssemblyError("media probe must implement probe")
        if not callable(getattr(concat_runner, "concat", None)):
            raise H3AssemblyError("concat runner must implement concat")
        self._probe = probe
        self._concat_runner = concat_runner

    def assemble(
        self,
        *,
        episode_revision_id: UUID,
        selection_authority_resolver: H3PersistedSelectionAuthorityResolver,
        artifact_resolver: H3ArtifactResolver,
        destination: Path,
    ) -> H3AssemblyManifest:
        if type(episode_revision_id) is not UUID:
            raise H3AssemblyError("episode revision id must be a UUID")
        if not callable(selection_authority_resolver):
            raise H3AssemblyError("persisted selection authority resolver is required")
        if not callable(artifact_resolver):
            raise H3AssemblyError("artifact resolver must be callable")
        try:
            segments = selection_authority_resolver(episode_revision_id)
        except H3AssemblyError:
            raise
        except Exception as exc:
            raise H3AssemblyError(
                "persisted selection authority resolver failed"
            ) from exc
        if type(segments) is not tuple or not segments or any(
            type(segment) is not H3SelectedSegment for segment in segments
        ):
            raise H3AssemblyError(
                "persisted selected segments must be a non-empty sealed tuple"
            )
        safe_destination = _validate_destination_path(destination)
        ordered_segments = tuple(sorted(segments, key=lambda segment: segment.ordinal))
        _validate_segment_sequence(ordered_segments)

        verified_sources: list[_VerifiedSource] = []
        segment_profiles: list[H3MediaProfile] = []
        seen_paths: set[Path] = set()
        for segment in ordered_segments:
            try:
                resolved = artifact_resolver(segment.artifact_id)
            except H3AssemblyError:
                raise
            except Exception as exc:
                raise H3AssemblyError("selected artifact resolver failed") from exc
            path = _validate_source_path(resolved)
            try:
                canonical_path = path.resolve(strict=True)
            except OSError as exc:  # pragma: no cover - validated immediately above
                raise H3AssemblyError("resolved artifact path cannot be resolved") from exc
            if canonical_path == safe_destination.resolve() or canonical_path in seen_paths:
                raise H3AssemblyError("selected artifacts must resolve to distinct sources")
            seen_paths.add(canonical_path)
            verified = _verify_source(path, segment.artifact_digest)
            try:
                profile = self._probe.probe(path)
            except H3AssemblyError:
                raise
            except Exception as exc:
                raise H3AssemblyError("media probe failed") from exc
            _validate_profile(profile)
            _ensure_source_unchanged(verified)
            verified_sources.append(verified)
            segment_profiles.append(profile)

        try:
            private_root = Path(
                tempfile.mkdtemp(
                    prefix=f".{safe_destination.stem}.h3-assembly-",
                    dir=safe_destination.parent,
                )
            )
        except OSError as exc:
            raise H3AssemblyError("private assembly staging cannot be created") from exc

        publish_temporary: Path | None = None
        try:
            staged_sources: list[_VerifiedSource] = []
            for segment, source in zip(
                ordered_segments, verified_sources, strict=True
            ):
                _ensure_source_unchanged(source)
                staged_path = private_root / (
                    f"{segment.ordinal:04d}-{segment.selected_attempt_id}.mp4"
                )
                try:
                    shutil.copyfile(source.path, staged_path)
                except OSError as exc:
                    raise H3AssemblyError(
                        "selected artifact cannot be copied into private staging"
                    ) from exc
                _ensure_source_unchanged(source)
                staged_sources.append(_verify_source(staged_path, source.digest))

            for source in (*verified_sources, *staged_sources):
                _ensure_source_unchanged(source)

            temporary_output = private_root / "assembled.mp4"
            try:
                result = self._concat_runner.concat(
                    tuple(source.path for source in staged_sources), temporary_output
                )
            except H3AssemblyError:
                raise
            except Exception as exc:
                raise H3AssemblyError("native-audio concat failed") from exc
            if result is not None:
                raise H3AssemblyError("concat runner must not return a result")

            for source in (*verified_sources, *staged_sources):
                _ensure_source_unchanged(source)

            final_path = _validate_source_path(temporary_output)
            final_snapshot = _verify_source(final_path, _sha256_file(final_path))
            try:
                final_profile = self._probe.probe(final_path)
            except H3AssemblyError:
                raise
            except Exception as exc:
                raise H3AssemblyError("final media probe failed") from exc
            _validate_profile(final_profile)
            _ensure_source_unchanged(final_snapshot)

            segment_durations = tuple(
                profile.duration_seconds for profile in segment_profiles
            )
            expected_duration = math.fsum(segment_durations)
            if not math.isclose(
                final_profile.duration_seconds,
                expected_duration,
                rel_tol=0.0,
                abs_tol=_DURATION_TOLERANCE_SECONDS,
            ):
                raise H3AssemblyError(
                    "final duration does not match selected segment durations"
                )
            _ensure_source_unchanged(final_snapshot)
            final_digest = final_snapshot.digest

            exception_segments = tuple(
                segment.ordinal
                for segment in ordered_segments
                if segment.qc_exception_codes
            )
            manifest_fields = dict(
                schema_version=_SCHEMA_VERSION,
                episode_revision_id=episode_revision_id,
                segments=ordered_segments,
                segment_duration_seconds=segment_durations,
                final_duration_seconds=final_profile.duration_seconds,
                output_artifact_digest=final_digest,
                qc_exception_segments=exception_segments,
                width=_WIDTH,
                height=_HEIGHT,
                fps=_FPS,
                video_codec=_VIDEO_CODEC,
                audio_codec=_AUDIO_CODEC,
                subtitles=False,
            )
            manifest_digest = _canonical_digest(_manifest_payload(**manifest_fields))
            manifest = H3AssemblyManifest(
                **manifest_fields, manifest_digest=manifest_digest
            )
            try:
                publish_fd, publish_name = tempfile.mkstemp(
                    prefix=f".{safe_destination.stem}.h3-publish-",
                    suffix=".mp4",
                    dir=safe_destination.parent,
                )
                os.close(publish_fd)
                publish_temporary = Path(publish_name)
                os.replace(temporary_output, publish_temporary)
            except OSError as exc:
                raise H3AssemblyError(
                    "verified final assembly cannot enter publication staging"
                ) from exc
            publish_snapshot = _verify_source(
                publish_temporary, final_snapshot.digest
            )

            try:
                shutil.rmtree(private_root)
            except OSError as exc:
                raise H3AssemblyError("private assembly staging cleanup failed") from exc
            private_root = None

            _ensure_source_unchanged(publish_snapshot)
            try:
                os.link(publish_temporary, safe_destination)
            except FileExistsError as exc:
                raise H3AssemblyError(
                    "assembly destination already exists at atomic publication"
                ) from exc
            except OSError as exc:
                raise H3AssemblyError(
                    "final assembly cannot be published atomically without clobbering"
                ) from exc
            try:
                publish_temporary.unlink()
            except OSError:
                # The no-clobber hard link is already the complete, verified
                # delivery. A scanner lock on the redundant private link must
                # not turn that successful atomic publication into a failure.
                # Operational cleanup may remove this final-output-only link;
                # all selected source staging was deleted before publication.
                publish_temporary = None
                return manifest
            publish_temporary = None
            return manifest
        finally:
            cleanup_failure: OSError | None = None
            if private_root is not None:
                try:
                    shutil.rmtree(private_root)
                except OSError as exc:
                    cleanup_failure = exc
            if publish_temporary is not None:
                try:
                    publish_temporary.unlink(missing_ok=True)
                except OSError as exc:
                    cleanup_failure = cleanup_failure or exc
            if cleanup_failure is not None:
                raise H3AssemblyError("H3 assembly cleanup failed") from cleanup_failure


__all__ = [
    "H3ArtifactResolver",
    "H3AssemblyAdapter",
    "H3AssemblyError",
    "H3AssemblyManifest",
    "H3ConcatRunner",
    "H3MediaProbeBackend",
    "H3MediaProfile",
    "H3PersistedSelectionAuthorityResolver",
    "H3SelectedSegment",
]
