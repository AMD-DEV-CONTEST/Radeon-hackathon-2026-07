"""Strict, path-free runner for durable H3 final assembly authority."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import TypeAlias
from uuid import UUID

from drama.atomic_factory import (
    FactoryArtifactGateway,
    FactoryCoreOutput,
    FactoryProducedArtifact,
)
from drama.h3.assembly import (
    H3AssemblyAdapter,
    H3AssemblyError,
    H3AssemblyManifest,
    H3MediaProfile,
    H3SelectedSegment,
)
from drama.h3.amd_runtime import H3FfprobeBackend, H3MediaProbe
from shared_contracts import AtomicArtifactRef, OperationRequest


H3FinalAssemblyAuthorityLoader: TypeAlias = Callable[
    [UUID, UUID], tuple[UUID, tuple[H3SelectedSegment, ...]]
]

_STRUCTURED_INPUTS = {
    "video_codec": "h264",
    "audio_codec": "aac",
    "audio_source": "h3_native",
    "subtitles": False,
}
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_PATH_NAMES = frozenset(
    {
        "path",
        "paths",
        "file",
        "files",
        "filepath",
        "filepaths",
        "filename",
        "filenames",
    }
)
_MAX_PATH_SCAN_NODES = 100_000


class H3FinalAssemblyError(H3AssemblyError):
    """The final-assembly request or injected authority failed closed."""


class H3AssemblyFfprobeBackend:
    """Adapt the pinned AMD ffprobe result to the final-assembly profile."""

    __slots__ = ("_backend",)

    def __init__(self, backend: H3FfprobeBackend | None = None) -> None:
        self._backend = backend or H3FfprobeBackend()

    def probe(self, path: Path) -> H3MediaProfile:
        try:
            result = self._backend.probe(path)
        except Exception as exc:
            raise H3FinalAssemblyError(
                "final-assembly ffprobe inspection failed"
            ) from exc
        if type(result) is not H3MediaProbe:
            raise H3FinalAssemblyError(
                "final-assembly ffprobe returned an invalid result"
            )
        return H3MediaProfile(
            width=result.width,
            height=result.height,
            fps=result.fps_numerator / result.fps_denominator,
            video_codec=result.video_codec,
            audio_codec=result.audio_codec or "",
            duration_seconds=result.duration_seconds,
            stream_types=("video", "audio"),
        )


class H3AssemblyFfmpegConcatRunner:
    """Losslessly concatenate verified H3 MP4s inside one private directory."""

    __slots__ = ("_executable", "_timeout_seconds")

    def __init__(
        self,
        executable: str = "ffmpeg",
        *,
        timeout_seconds: int = 900,
    ) -> None:
        if (
            type(executable) is not str
            or not executable.strip()
            or type(timeout_seconds) is not int
            or timeout_seconds <= 0
        ):
            raise H3FinalAssemblyError(
                "final-assembly ffmpeg configuration is invalid"
            )
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def concat(self, inputs: tuple[Path, ...], destination: Path) -> None:
        if (
            type(inputs) is not tuple
            or not inputs
            or not isinstance(destination, Path)
            or destination.exists()
            or any(not isinstance(path, Path) for path in inputs)
            or any(path.parent != destination.parent for path in inputs)
            or len(set(inputs)) != len(inputs)
            or any(
                not re.fullmatch(r"[A-Za-z0-9._-]+", path.name)
                for path in (*inputs, destination)
            )
        ):
            raise H3FinalAssemblyError(
                "final-assembly concat paths are outside private staging"
            )
        manifest = destination.parent / "concat-inputs.txt"
        if manifest.exists():
            raise H3FinalAssemblyError(
                "final-assembly concat manifest already exists"
            )
        descriptor = -1
        try:
            descriptor = os.open(
                manifest,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                descriptor = -1
                for path in inputs:
                    handle.write(f"file '{path.name}'\n")
                handle.flush()
                os.fsync(handle.fileno())
            completed = subprocess.run(
                [
                    self._executable,
                    "-v",
                    "error",
                    "-nostdin",
                    "-n",
                    "-f",
                    "concat",
                    "-safe",
                    "1",
                    "-i",
                    manifest.name,
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    destination.name,
                ],
                cwd=destination.parent,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
            )
            if completed.returncode != 0 or not destination.is_file():
                raise H3FinalAssemblyError(
                    "final-assembly ffmpeg concat failed"
                )
            with destination.open("rb+") as handle:
                os.fsync(handle.fileno())
        except H3FinalAssemblyError:
            destination.unlink(missing_ok=True)
            raise
        except (OSError, subprocess.TimeoutExpired) as exc:
            destination.unlink(missing_ok=True)
            raise H3FinalAssemblyError(
                "final-assembly ffmpeg concat could not complete"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            manifest.unlink(missing_ok=True)


def _normalized_key(value: object) -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value).strip())
    return re.sub(r"[^a-z0-9]+", "_", separated.casefold()).strip("_")


def _path_key(value: object) -> bool:
    normalized = _normalized_key(value)
    return normalized in _PATH_NAMES or normalized.endswith(
        tuple(f"_{name}" for name in _PATH_NAMES)
    )


def _path_value(value: str) -> bool:
    candidate = value.strip()
    lowered = candidate.casefold()
    return bool(
        candidate
        and (
            _WINDOWS_ABSOLUTE_PATH.match(candidate)
            or candidate.startswith(("/", "\\\\", "~/", "~\\"))
            or lowered.startswith("file:")
            or "\\" in candidate
            or any(part in {".", ".."} for part in candidate.split("/"))
        )
    )


def _reject_paths(value: object, *, location: str) -> None:
    pending = [value]
    seen_containers: set[int] = set()
    nodes = 0
    while pending:
        current = pending.pop()
        nodes += 1
        if nodes > _MAX_PATH_SCAN_NODES:
            raise H3FinalAssemblyError(
                f"{location} exceeds the path-free validation limit"
            )
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in seen_containers:
                raise H3FinalAssemblyError(
                    f"{location} contains cyclic or aliased containers"
                )
            seen_containers.add(identity)
            for key, child in current.items():
                if _path_key(key):
                    raise H3FinalAssemblyError(
                        f"{location} contains a forbidden path field"
                    )
                pending.append(child)
        elif isinstance(current, (list, tuple)):
            identity = id(current)
            if identity in seen_containers:
                raise H3FinalAssemblyError(
                    f"{location} contains cyclic or aliased containers"
                )
            seen_containers.add(identity)
            pending.extend(current)
        elif isinstance(current, str) and _path_value(current):
            raise H3FinalAssemblyError(
                f"{location} contains a forbidden path value"
            )


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise H3FinalAssemblyError(
            "assembly manifest cannot be encoded as canonical JSON"
        ) from exc


def _sequence_source(segment: H3SelectedSegment) -> dict[str, object]:
    return {
        "ordinal": segment.ordinal,
        "sequence_id": str(segment.sequence_id),
        "sequence_revision_id": str(segment.sequence_revision_id),
        "selected_attempt_id": str(segment.selected_attempt_id),
        "selected_attempt_ordinal": segment.selected_attempt_ordinal,
        "artifact_id": str(segment.artifact_id),
        "artifact_digest": segment.artifact_digest,
        "authority_digest": segment.authority_digest,
    }


def _manifest_payload(manifest: H3AssemblyManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "episode_revision_id": str(manifest.episode_revision_id),
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
            for segment in manifest.segments
        ],
        "segment_duration_seconds": list(manifest.segment_duration_seconds),
        "final_duration_seconds": manifest.final_duration_seconds,
        "output_artifact_digest": manifest.output_artifact_digest,
        "qc_exception_segments": list(manifest.qc_exception_segments),
        "width": manifest.width,
        "height": manifest.height,
        "fps": manifest.fps,
        "video_codec": manifest.video_codec,
        "audio_codec": manifest.audio_codec,
        "subtitles": manifest.subtitles,
        "manifest_digest": manifest.manifest_digest,
    }


def _verify_authority(
    value: object,
) -> tuple[UUID, tuple[H3SelectedSegment, ...]]:
    if type(value) is not tuple or len(value) != 2:
        raise H3FinalAssemblyError(
            "persisted final-assembly authority has an invalid envelope"
        )
    episode_revision_id, segments = value
    if type(episode_revision_id) is not UUID:
        raise H3FinalAssemblyError(
            "persisted final-assembly episode revision is invalid"
        )
    if (
        type(segments) is not tuple
        or not segments
        or any(type(segment) is not H3SelectedSegment for segment in segments)
    ):
        raise H3FinalAssemblyError(
            "persisted final-assembly segments are invalid"
        )
    try:
        segments = tuple(replace(segment) for segment in segments)
    except H3AssemblyError as exc:
        raise H3FinalAssemblyError(
            "persisted final-assembly segment authority is invalid"
        ) from exc
    if tuple(segment.ordinal for segment in segments) != tuple(
        range(1, len(segments) + 1)
    ):
        raise H3FinalAssemblyError(
            "persisted final-assembly segments are missing or reordered"
        )
    if any(
        segment.ordinal > 999 or segment.selected_attempt_ordinal not in {0, 1}
        for segment in segments
    ):
        raise H3FinalAssemblyError(
            "persisted final-assembly sequence identity is outside the pinned profile"
        )
    if len({segment.artifact_id for segment in segments}) != len(segments):
        raise H3FinalAssemblyError(
            "persisted final-assembly artifact identities are not unique"
        )
    return episode_revision_id, segments


def _verify_structured_inputs(value: Mapping[str, object]) -> None:
    supplied = dict(value)
    if set(supplied) != set(_STRUCTURED_INPUTS) or any(
        type(supplied[key]) is not type(expected)
        or supplied[key] != expected
        for key, expected in _STRUCTURED_INPUTS.items()
    ):
        raise H3FinalAssemblyError(
            "final-assembly structured inputs do not match the pinned profile"
        )


def _verify_refs(
    request: OperationRequest,
    segments: tuple[H3SelectedSegment, ...],
) -> tuple[AtomicArtifactRef, ...]:
    refs = request.input_artifact_refs
    if len(refs) != len(segments):
        raise H3FinalAssemblyError(
            "final-assembly input artifacts are missing or unexpected"
        )
    artifact_ids: set[UUID] = set()
    roles: set[str] = set()
    for ref, segment in zip(refs, segments, strict=True):
        expected_role = (
            f"h3.sequence.{segment.ordinal:03d}.attempt."
            f"{segment.selected_attempt_ordinal}.video"
        )
        if not isinstance(ref, AtomicArtifactRef):
            raise H3FinalAssemblyError(
                "final-assembly input artifact reference is invalid"
            )
        if (
            ref.project_id != request.project_id
            or ref.artifact_id != segment.artifact_id
            or ref.mime_type != "video/mp4"
            or ref.logical_role != expected_role
            or type(ref.byte_size) is not int
            or ref.byte_size <= 0
            or not hmac.compare_digest(
                str(ref.content_digest), segment.artifact_digest
            )
        ):
            raise H3FinalAssemblyError(
                "final-assembly input artifact does not match selected authority"
            )
        if ref.artifact_id in artifact_ids or ref.logical_role in roles:
            raise H3FinalAssemblyError(
                "final-assembly input artifacts must be unique and ordered"
            )
        artifact_ids.add(ref.artifact_id)
        roles.add(ref.logical_role)
    return refs


def _write_verified_source(
    root: Path,
    *,
    ref: AtomicArtifactRef,
    ordinal: int,
    reader: Callable[[AtomicArtifactRef], bytes],
) -> Path:
    try:
        payload = reader(ref)
    except Exception as exc:
        raise H3FinalAssemblyError("final-assembly artifact read failed") from exc
    if type(payload) is not bytes:
        raise H3FinalAssemblyError(
            "final-assembly artifact gateway must return bytes"
        )
    if len(payload) != ref.byte_size:
        raise H3FinalAssemblyError(
            "final-assembly artifact byte size verification failed"
        )
    digest = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(digest, str(ref.content_digest)):
        raise H3FinalAssemblyError(
            "final-assembly artifact digest verification failed"
        )

    destination = root / f"source-{ordinal:04d}.mp4"
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        stat = destination.stat()
        staged_digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    except OSError as exc:
        raise H3FinalAssemblyError(
            "final-assembly private source staging failed"
        ) from exc
    if (
        stat.st_size != ref.byte_size
        or not hmac.compare_digest(staged_digest, str(ref.content_digest))
    ):
        raise H3FinalAssemblyError(
            "final-assembly private source staging verification failed"
        )
    return destination


class H3FinalAssemblyRunner:
    """Convert sealed H3 selection refs into two path-free core artifacts."""

    __slots__ = ("_assembly_adapter", "_authority_loader")

    def __init__(
        self,
        *,
        authority_loader: H3FinalAssemblyAuthorityLoader,
        assembly_adapter: H3AssemblyAdapter,
    ) -> None:
        if not callable(authority_loader):
            raise H3FinalAssemblyError(
                "final-assembly authority loader must be callable"
            )
        if not isinstance(assembly_adapter, H3AssemblyAdapter):
            raise H3FinalAssemblyError(
                "final-assembly adapter must be H3AssemblyAdapter"
            )
        self._authority_loader = authority_loader
        self._assembly_adapter = assembly_adapter

    def run(
        self,
        request: OperationRequest,
        artifacts: FactoryArtifactGateway,
        /,
    ) -> FactoryCoreOutput:
        if not isinstance(request, OperationRequest):
            raise H3FinalAssemblyError(
                "final-assembly runner requires an OperationRequest"
            )
        if request.op_type != "final.assemble":
            raise H3FinalAssemblyError(
                "final-assembly runner only accepts final.assemble"
            )
        _verify_structured_inputs(request.structured_inputs)
        _reject_paths(request.structured_inputs, location="structured inputs")
        _reject_paths(request.parameter_snapshot, location="parameter snapshot")
        if not isinstance(artifacts, FactoryArtifactGateway):
            raise H3FinalAssemblyError(
                "final-assembly artifact gateway is invalid"
            )

        try:
            loaded = self._authority_loader(
                request.project_id, request.workflow_run_id
            )
        except H3FinalAssemblyError:
            raise
        except Exception as exc:
            raise H3FinalAssemblyError(
                "persisted final-assembly authority could not be loaded"
            ) from exc
        episode_revision_id, segments = _verify_authority(loaded)
        refs = _verify_refs(request, segments)

        try:
            temporary = tempfile.TemporaryDirectory(
                prefix="creative-hub-h3-final-"
            )
        except OSError as exc:
            raise H3FinalAssemblyError(
                "final-assembly private staging could not be created"
            ) from exc

        with temporary as raw_root:
            root = Path(raw_root)
            try:
                os.chmod(root, 0o700)
            except OSError as exc:
                raise H3FinalAssemblyError(
                    "final-assembly private staging permissions could not be pinned"
                ) from exc
            by_artifact: dict[UUID, Path] = {}
            reader = artifacts.read_bytes
            for segment, ref in zip(segments, refs, strict=True):
                by_artifact[ref.artifact_id] = _write_verified_source(
                    root,
                    ref=ref,
                    ordinal=segment.ordinal,
                    reader=reader,
                )

            def selection_resolver(value: UUID) -> tuple[H3SelectedSegment, ...]:
                if value != episode_revision_id:
                    raise H3FinalAssemblyError(
                        "assembly adapter requested an unexpected episode revision"
                    )
                return segments

            def artifact_resolver(value: UUID) -> Path:
                try:
                    return by_artifact[value]
                except KeyError as exc:
                    raise H3FinalAssemblyError(
                        "assembly adapter requested an unselected artifact"
                    ) from exc

            destination = root / "final_episode.mp4"
            try:
                manifest = self._assembly_adapter.assemble(
                    episode_revision_id=episode_revision_id,
                    selection_authority_resolver=selection_resolver,
                    artifact_resolver=artifact_resolver,
                    destination=destination,
                )
            except H3FinalAssemblyError:
                raise
            except H3AssemblyError as exc:
                raise H3FinalAssemblyError("H3 final assembly failed") from exc
            except Exception as exc:
                raise H3FinalAssemblyError(
                    "H3 final assembly adapter failed"
                ) from exc

            if type(manifest) is not H3AssemblyManifest:
                raise H3FinalAssemblyError(
                    "H3 final assembly adapter returned an invalid manifest"
                )
            if manifest.episode_revision_id != episode_revision_id:
                raise H3FinalAssemblyError(
                    "H3 final assembly manifest episode identity mismatch"
                )
            if manifest.segments != segments:
                raise H3FinalAssemblyError(
                    "H3 final assembly manifest selection authority mismatch"
                )
            if manifest.recompute_digest() != manifest.manifest_digest:
                raise H3FinalAssemblyError(
                    "H3 final assembly manifest digest mismatch"
                )
            try:
                final_episode = destination.read_bytes()
                final_size = destination.stat().st_size
            except OSError as exc:
                raise H3FinalAssemblyError(
                    "H3 final episode output is unavailable"
                ) from exc
            final_digest = hashlib.sha256(final_episode).hexdigest()
            if (
                not final_episode
                or final_size != len(final_episode)
                or not hmac.compare_digest(
                    final_digest, manifest.output_artifact_digest
                )
            ):
                raise H3FinalAssemblyError(
                    "H3 final episode output verification failed"
                )

            manifest_value = _manifest_payload(manifest)
            _reject_paths(manifest_value, location="assembly manifest")
            manifest_bytes = _canonical_json_bytes(manifest_value)
            structured_output = {
                "schema_version": manifest.schema_version,
                "manifest_digest": manifest.manifest_digest,
                "output_artifact_digest": manifest.output_artifact_digest,
                "duration_seconds": manifest.final_duration_seconds,
                "episode_revision_id": str(manifest.episode_revision_id),
                "sequence_sources": [
                    _sequence_source(segment) for segment in manifest.segments
                ],
            }
            _reject_paths(structured_output, location="structured output")

        return FactoryCoreOutput(
            artifacts=(
                FactoryProducedArtifact(
                    payload=final_episode,
                    mime_type="video/mp4",
                    logical_role="final_episode",
                ),
                FactoryProducedArtifact(
                    payload=manifest_bytes,
                    mime_type="application/json",
                    logical_role="assembly_manifest",
                ),
            ),
            structured_output=structured_output,
        )


__all__ = [
    "H3AssemblyFfmpegConcatRunner",
    "H3AssemblyFfprobeBackend",
    "H3FinalAssemblyAuthorityLoader",
    "H3FinalAssemblyError",
    "H3FinalAssemblyRunner",
]
