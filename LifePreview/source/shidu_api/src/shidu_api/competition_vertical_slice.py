from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from creative_hub.artifact_publication import (
    ArtifactPublicationService,
    ArtifactStatus,
    ContentAddressedArtifactStore,
    PostgresArtifactRepository,
)
from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.models import (
    ArtifactRecordRow,
    DeliveryRevisionRecord,
    OperationAttemptRecord,
    OperationAttemptStateRecord,
    OperationRunRecord,
    VideoJobProjectionRecord,
)
from creative_hub.db.repositories import OperationRepository
from shared_contracts import RetentionClass
from shidu_api.competition_vertical_slice_worker import ClickedDeferredVideoJob

SessionFactory = Callable[[], Session]
_SCHEMA = "amd.competition-vertical-slice.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUNNER_IMPLEMENTATION_DIGEST = hashlib.sha256(
    b"amd.three-second-runner.v1|73frames|native-audio|no-subtitles"
).hexdigest()
_FRAME_COUNT_WARNING = "ACTUAL_FRAME_COUNT_DEVIATES_FROM_REQUESTED_73"
_FPS_WARNING = "ACTUAL_FPS_DEVIATES_FROM_REQUESTED_24"
_DURATION_WARNING = "ACTUAL_DURATION_DEVIATES_FROM_EXPECTED_73_OVER_24"


class CompetitionVerticalSliceError(RuntimeError):
    """The clicked vertical-slice result cannot be published truthfully."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_digest(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CompetitionVerticalSliceError(f"{field} must be a lowercase SHA-256")
    return value


def _validated_media_authority(
    probe: object,
    media_warnings: object,
) -> tuple[float, int, float, int, int, int, tuple[str, ...]]:
    if not isinstance(probe, dict):
        raise CompetitionVerticalSliceError("runner media authority is invalid")
    duration = probe.get("duration_seconds")
    fps = probe.get("fps")
    frame_count = probe.get("frame_count")
    video_streams = probe.get("video_streams")
    audio_streams = probe.get("audio_streams")
    subtitle_streams = probe.get("subtitle_streams")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not 2.8 <= float(duration) <= 3.5
        or isinstance(fps, bool)
        or not isinstance(fps, (int, float))
        or not 20.0 <= float(fps) <= 30.0
        or type(frame_count) is not int
        or not 65 <= frame_count <= 90
        or type(video_streams) is not int
        or video_streams != 1
        or type(audio_streams) is not int
        or audio_streams < 1
        or type(subtitle_streams) is not int
        or subtitle_streams != 0
        or "mp4" not in str(probe.get("format_name", "")).casefold()
    ):
        raise CompetitionVerticalSliceError("runner media authority is invalid")
    if not math.isclose(
        frame_count / float(fps),
        float(duration),
        rel_tol=0.0,
        abs_tol=0.35,
    ):
        raise CompetitionVerticalSliceError("runner media authority is invalid")
    expected: list[str] = []
    if frame_count != 73:
        expected.append(_FRAME_COUNT_WARNING)
    if not math.isclose(float(fps), 24.0, rel_tol=0.0, abs_tol=0.01):
        expected.append(_FPS_WARNING)
    if not math.isclose(float(duration), 73 / 24, rel_tol=0.0, abs_tol=0.25):
        expected.append(_DURATION_WARNING)
    if media_warnings != expected:
        raise CompetitionVerticalSliceError("runner media warnings are invalid")
    return (
        float(duration),
        frame_count,
        float(fps),
        video_streams,
        audio_streams,
        subtitle_streams,
        tuple(expected),
    )


def _load_runner_result(
    checkpoint_path: Path,
    *,
    result_path: Path,
    result_sha256: str,
    expected_digest: str,
    expected_job_authority_digest: str,
) -> dict[str, Any]:
    """Load the runner's durable success authority, not caller assertions."""

    checkpoint = Path(checkpoint_path)
    if checkpoint.is_symlink():
        raise CompetitionVerticalSliceError("runner checkpoint symlinks are forbidden")
    try:
        checkpoint = checkpoint.resolve(strict=True)
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompetitionVerticalSliceError("runner checkpoint is unavailable") from exc
    job_authority = _strict_digest(
        expected_job_authority_digest,
        "expected_job_authority_digest",
    )
    expected_root = checkpoint.parent
    if (
        expected_root.name != job_authority
        or expected_root.parent.name != "jobs"
        or expected_root.parent.parent.name != "vertical-slice"
    ):
        raise CompetitionVerticalSliceError(
            "runner checkpoint is not bound to the clicked job"
        )
    expected_prompt = str(
        uuid5(NAMESPACE_URL, f"amd-three-second-prompt:{job_authority}")
    )
    expected_nonce = hashlib.sha256(
        f"amd-three-second-nonce:{job_authority}".encode()
    ).hexdigest()[:32]
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != "amd.three-second-runner.v1"
        or payload.get("status") != "succeeded"
        or payload.get("logicalPromptId") != expected_prompt
        or payload.get("clickSubmissionNonce") != expected_nonce
        or payload.get("requestedDurationSeconds") != 3.0
        or payload.get("frameCount") != 73
        or payload.get("fps") != 24
        or payload.get("nativeAudio") is not True
        or payload.get("subtitles") is not False
        or not isinstance(payload.get("h3"), dict)
        or not isinstance(payload.get("result"), dict)
    ):
        raise CompetitionVerticalSliceError("runner checkpoint is not succeeded")
    result = dict(payload["result"])
    h3 = payload["h3"]
    if not hmac.compare_digest(canonical_json_digest(result), expected_digest):
        raise CompetitionVerticalSliceError("runner result digest mismatch")
    if (
        result.get("requestedDurationSeconds") != 3.0
        or result.get("frameCount") != 73
        or result.get("fps") != 24
        or result.get("nativeAudio") is not True
        or result.get("subtitles") is not False
        or result.get("outputPath") != str(result_path)
        or result.get("outputSha256") != result_sha256
        or result.get("promptId") != h3.get("promptId")
        or result.get("submissionNonce") != expected_nonce
        or result.get("submissionNonce") != h3.get("submissionNonce")
        or h3.get("status") != "succeeded"
        or h3.get("outputPath") != str(result_path)
        or h3.get("outputSha256") != result_sha256
        or result.get("workflowSha256") != h3.get("workflowSha256")
        or _SHA256_RE.fullmatch(str(result.get("workflowSha256", ""))) is None
    ):
        raise CompetitionVerticalSliceError("runner media authority is invalid")
    _validated_media_authority(result.get("ffprobe"), result.get("mediaWarnings"))
    return result


def _existing_envelope_matches(
    session: Session,
    *,
    project_id: UUID,
    workflow_run_id: UUID,
    video_job_projection_id: UUID,
    job_id: str,
    job_payload: dict[str, Any],
    envelope: object,
    content_digest: str,
    byte_size: int,
    runner_result_digest: str,
    runner_result: dict[str, Any],
    input_authority_digest: str,
    h3_execution_authority_sha256: str,
) -> dict[str, Any] | None:
    if envelope is None:
        return None
    if not isinstance(envelope, dict):
        raise CompetitionVerticalSliceError("delivery replay authority is invalid")
    try:
        replay_artifact_id = UUID(str(envelope.get("artifactId")))
    except (TypeError, ValueError) as exc:
        raise CompetitionVerticalSliceError(
            "delivery replay artifact identity is invalid"
        ) from exc
    media = _validated_media_authority(
        runner_result.get("ffprobe"),
        runner_result.get("mediaWarnings"),
    )
    expected = build_competition_vertical_slice_envelope(
        artifact_id=replay_artifact_id,
        artifact_digest=content_digest,
        byte_size=byte_size,
        runner_result_digest=runner_result_digest,
        actual_duration_seconds=media[0],
        actual_frame_count=media[1],
        actual_fps=media[2],
        actual_video_streams=media[3],
        actual_audio_streams=media[4],
        actual_subtitle_streams=media[5],
        media_warnings=media[6],
    )
    if envelope != expected:
        raise CompetitionVerticalSliceError("delivery envelope changed on replay")
    artifact = session.scalar(
        select(ArtifactRecordRow).where(
            ArtifactRecordRow.id == UUID(expected["artifactId"]),
            ArtifactRecordRow.project_id == project_id,
            ArtifactRecordRow.status == "COMMITTED",
        )
    )
    operation = None if artifact is None else session.scalar(
        select(OperationRunRecord).where(
            OperationRunRecord.id == artifact.operation_run_id,
            OperationRunRecord.project_id == project_id,
        )
    )
    attempt = None if artifact is None else session.scalar(
        select(OperationAttemptRecord).where(
            OperationAttemptRecord.id == artifact.operation_attempt_id,
            OperationAttemptRecord.project_id == project_id,
        )
    )
    state = None if artifact is None else session.scalar(
        select(OperationAttemptStateRecord).where(
            OperationAttemptStateRecord.attempt_id == artifact.operation_attempt_id,
            OperationAttemptStateRecord.project_id == project_id,
        )
    )
    actual_media = {
        "durationSeconds": media[0],
        "frameCount": media[1],
        "fps": media[2],
        "videoStreams": media[3],
        "audioStreams": media[4],
        "subtitleStreams": media[5],
        "warnings": list(media[6]),
    }
    expected_request = {
        "schemaVersion": "amd.competition-direct-h3-attempt.v1",
        "jobId": job_id,
        "workflowRunId": str(workflow_run_id),
        "requestedDurationSeconds": 3.0,
        "frameCount": 73,
        "fps": 24,
        "nativeAudio": True,
        "subtitles": False,
        "resultSha256": content_digest,
        "runnerResultDigest": runner_result_digest,
        "inputAuthorityDigest": input_authority_digest,
        "h3ExecutionAuthoritySha256": h3_execution_authority_sha256,
        "actualMedia": actual_media,
    }
    if (
        artifact is None
        or operation is None
        or attempt is None
        or state is None
        or operation.workflow_run_id != workflow_run_id
        or operation.status != "SUCCEEDED"
        or operation.accepted_attempt_id != artifact.operation_attempt_id
        or artifact.content_digest != content_digest
        or artifact.byte_size != byte_size
        or artifact.mime_type != "video/mp4"
        or artifact.logical_role != "final_episode"
        or artifact.publication_key != f"competition-three-second:{job_id}"
        or attempt.operation_run_id != operation.id
        or attempt.worker_id != "amd.competition-vertical-slice"
        or attempt.implementation_digest != _RUNNER_IMPLEMENTATION_DIGEST
        or attempt.request_payload != expected_request
        or state.status != "SUCCEEDED"
        or state.stage != "COMMITTED"
    ):
        raise CompetitionVerticalSliceError("delivery replay artifact is invalid")
    try:
        delivery_id = UUID(str(job_payload["competitionVerticalSliceDeliveryId"]))
        delivery_digest = _strict_digest(
            job_payload["competitionVerticalSliceDeliveryDigest"],
            "competition delivery digest",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CompetitionVerticalSliceError(
            "delivery replay record is unavailable"
        ) from exc
    delivery_payload = {
        "schema_version": "amd.competition-vertical-slice-delivery.v1",
        "workflow_run_id": str(workflow_run_id),
        "video_job_projection_id": str(video_job_projection_id),
        "job_id": job_id,
        "envelope": expected,
    }
    delivery = session.get(DeliveryRevisionRecord, delivery_id)
    if (
        delivery is None
        or delivery.project_id != project_id
        or delivery.digest != delivery_digest
        or canonical_json_digest(delivery_payload) != delivery_digest
        or delivery.payload != delivery_payload
        or delivery.created_by_actor != "amd.competition-vertical-slice"
    ):
        raise CompetitionVerticalSliceError("delivery replay record is invalid")
    return dict(envelope)


def build_competition_vertical_slice_envelope(
    *,
    artifact_id: UUID,
    artifact_digest: str,
    byte_size: int,
    runner_result_digest: str,
    actual_duration_seconds: float,
    actual_frame_count: int,
    actual_fps: float,
    actual_video_streams: int,
    actual_audio_streams: int,
    actual_subtitle_streams: int,
    media_warnings: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(artifact_id, UUID):
        raise CompetitionVerticalSliceError("artifact_id must be a UUID")
    _strict_digest(artifact_digest, "artifact_digest")
    _strict_digest(runner_result_digest, "runner_result_digest")
    if type(byte_size) is not int or byte_size <= 0:
        raise CompetitionVerticalSliceError("byte_size must be positive")
    media = _validated_media_authority(
        {
            "duration_seconds": actual_duration_seconds,
            "frame_count": actual_frame_count,
            "fps": actual_fps,
            "video_streams": actual_video_streams,
            "audio_streams": actual_audio_streams,
            "subtitle_streams": actual_subtitle_streams,
            "format_name": "mp4",
        },
        list(media_warnings),
    )
    identity: dict[str, Any] = {
        "schemaVersion": _SCHEMA,
        "artifactId": str(artifact_id),
        "artifactDigest": artifact_digest,
        "byteSize": byte_size,
        "mimeType": "video/mp4",
        "logicalRole": "final_episode",
        "requestedDurationSeconds": 3.0,
        "frameCount": 73,
        "fps": 24,
        "nativeAudio": True,
        "subtitles": False,
        "actualDurationSeconds": media[0],
        "actualFrameCount": media[1],
        "actualFps": media[2],
        "actualVideoStreams": media[3],
        "actualAudioStreams": media[4],
        "actualSubtitleStreams": media[5],
        "mediaWarnings": list(media[6]),
        "runnerResultDigest": runner_result_digest,
    }
    return {**identity, "envelopeDigest": canonical_json_digest(identity)}


def publish_competition_vertical_slice(
    *,
    session_factory: SessionFactory,
    cas_root: Path,
    project_id: UUID,
    job_id: str,
    result_path: Path,
    runner_checkpoint_path: Path,
    runner_result_digest: str,
    expected_job_authority_digest: str,
    expected_input_authority_digest: str,
    expected_h3_execution_authority_sha256: str,
) -> dict[str, Any]:
    """Publish one verified 73-frame MP4 and atomically expose it to the API.

    This competition path intentionally does not pretend the unconfigured H3
    DAG handlers ran.  It uses the materialized H3 sequence operation as the
    durable fence while the direct AMD runner performs the real ComfyUI call.
    """

    if not isinstance(project_id, UUID):
        raise CompetitionVerticalSliceError("project_id must be a UUID")
    if not isinstance(job_id, str) or not job_id.strip():
        raise CompetitionVerticalSliceError("job_id is required")
    _strict_digest(runner_result_digest, "runner_result_digest")
    job_authority_digest = _strict_digest(
        expected_job_authority_digest,
        "expected_job_authority_digest",
    )
    input_authority_digest = _strict_digest(
        expected_input_authority_digest,
        "expected_input_authority_digest",
    )
    execution_authority_sha256 = _strict_digest(
        expected_h3_execution_authority_sha256,
        "expected_h3_execution_authority_sha256",
    )
    video = Path(result_path)
    if video.is_symlink():
        raise CompetitionVerticalSliceError("result symlinks are forbidden")
    try:
        video = video.resolve(strict=True)
    except OSError as exc:
        raise CompetitionVerticalSliceError("result MP4 is unavailable") from exc
    if not video.is_file() or video.suffix.casefold() != ".mp4":
        raise CompetitionVerticalSliceError("result must be an MP4 file")
    byte_size = video.stat().st_size
    if byte_size <= 0:
        raise CompetitionVerticalSliceError("result MP4 is empty")
    with video.open("rb") as handle:
        header = handle.read(32)
    if b"ftyp" not in header:
        raise CompetitionVerticalSliceError("result is not an ISO-BMFF MP4")
    content_digest = _sha256_file(video)
    runner_result = _load_runner_result(
        runner_checkpoint_path,
        result_path=video,
        result_sha256=content_digest,
        expected_digest=runner_result_digest,
        expected_job_authority_digest=job_authority_digest,
    )
    actual_media = _validated_media_authority(
        runner_result.get("ffprobe"),
        runner_result.get("mediaWarnings"),
    )

    with session_factory() as session, session.begin():
        job = session.scalar(
            select(VideoJobProjectionRecord)
            .where(
                VideoJobProjectionRecord.project_id == project_id,
                VideoJobProjectionRecord.external_job_id == job_id,
            )
            .with_for_update()
        )
        if job is None:
            raise CompetitionVerticalSliceError("clicked video job is unavailable")
        try:
            clicked = ClickedDeferredVideoJob.from_projection_record(job)
        except Exception as exc:
            raise CompetitionVerticalSliceError(
                "clicked video job authority is invalid"
            ) from exc
        if not hmac.compare_digest(clicked.authority_digest, job_authority_digest):
            raise CompetitionVerticalSliceError(
                "runner result belongs to a different clicked job"
            )
        payload = dict(job.payload)
        if (
            payload.get("pipelineMode") != "h3_vertical_slice"
            or payload.get("targetDurationSeconds") != 3.0
            or payload.get("sequenceCount") != 1
        ):
            raise CompetitionVerticalSliceError("video job is not ready for publication")
        try:
            workflow_run_id = UUID(str(payload["workflowRunId"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise CompetitionVerticalSliceError("H3 workflow identity is unavailable") from exc
        replay = _existing_envelope_matches(
            session,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            video_job_projection_id=job.id,
            job_id=job_id,
            job_payload=payload,
            envelope=payload.get("competitionVerticalSlice"),
            content_digest=content_digest,
            byte_size=byte_size,
            runner_result_digest=runner_result_digest,
            runner_result=runner_result,
            input_authority_digest=input_authority_digest,
            h3_execution_authority_sha256=execution_authority_sha256,
        )
        if replay is not None:
            return replay
        operation = session.scalar(
            select(OperationRunRecord)
            .where(
                OperationRunRecord.project_id == project_id,
                OperationRunRecord.workflow_run_id == workflow_run_id,
                OperationRunRecord.node_key == "sequence.001.execute",
                OperationRunRecord.op_type == "h3.sequence.execute",
            )
            .with_for_update()
        )
        if operation is None:
            raise CompetitionVerticalSliceError("H3 sequence operation is unavailable")
        attempt_id = uuid5(
            NAMESPACE_URL,
            f"amd-competition-attempt:{project_id}:{workflow_run_id}:{content_digest}",
        )
        submission_nonce = uuid5(
            NAMESPACE_URL,
            f"amd-competition-nonce:{project_id}:{workflow_run_id}:{content_digest}",
        )
        request_payload = {
            "schemaVersion": "amd.competition-direct-h3-attempt.v1",
            "jobId": job_id,
            "workflowRunId": str(workflow_run_id),
            "requestedDurationSeconds": 3.0,
            "frameCount": 73,
            "fps": 24,
            "nativeAudio": True,
            "subtitles": False,
            "resultSha256": content_digest,
            "runnerResultDigest": runner_result_digest,
            "inputAuthorityDigest": input_authority_digest,
            "h3ExecutionAuthoritySha256": execution_authority_sha256,
            "actualMedia": {
                "durationSeconds": actual_media[0],
                "frameCount": actual_media[1],
                "fps": actual_media[2],
                "videoStreams": actual_media[3],
                "audioStreams": actual_media[4],
                "subtitleStreams": actual_media[5],
                "warnings": list(actual_media[6]),
            },
        }
        operations = OperationRepository(session)
        attempt = operations.create_attempt(
            project_id=project_id,
            operation_run_id=operation.id,
            attempt_number=1,
            fencing_token=1,
            worker_id="amd.competition-vertical-slice",
            implementation_digest=_RUNNER_IMPLEMENTATION_DIGEST,
            request_payload=request_payload,
            submission_nonce=submission_nonce,
            attempt_id=attempt_id,
        ).value
        state = session.get(OperationAttemptStateRecord, attempt.id)
        if state is None:
            raise CompetitionVerticalSliceError("H3 attempt state is unavailable")
        if state.status not in {"PREPARED", "SUCCEEDED"}:
            raise CompetitionVerticalSliceError("H3 attempt is not publishable")
        if operation.accepted_attempt_id not in {None, attempt.id}:
            raise CompetitionVerticalSliceError(
                "H3 operation accepted a different attempt"
            )
        operation_run_id = operation.id

    publication = ArtifactPublicationService(
        repository=PostgresArtifactRepository(session_factory),
        store=ContentAddressedArtifactStore(Path(cas_root)),
    )
    with video.open("rb") as stream:
        artifact = publication.publish(
            project_id=project_id,
            operation_run_id=operation_run_id,
            attempt_id=attempt_id,
            attempt_number=1,
            fencing_token=1,
            publication_key=f"competition-three-second:{job_id}",
            stream=stream,
            mime_type="video/mp4",
            logical_role="final_episode",
            retention_class=RetentionClass.CANON,
            expected_digest=content_digest,
            expected_size=byte_size,
        )
    if artifact.status is not ArtifactStatus.COMMITTED:
        raise CompetitionVerticalSliceError("final MP4 did not commit to CAS")
    envelope = build_competition_vertical_slice_envelope(
        artifact_id=artifact.artifact_id,
        artifact_digest=artifact.content_digest,
        byte_size=artifact.byte_size,
        runner_result_digest=runner_result_digest,
        actual_duration_seconds=actual_media[0],
        actual_frame_count=actual_media[1],
        actual_fps=actual_media[2],
        actual_video_streams=actual_media[3],
        actual_audio_streams=actual_media[4],
        actual_subtitle_streams=actual_media[5],
        media_warnings=actual_media[6],
    )

    with session_factory() as session, session.begin():
        job = session.scalar(
            select(VideoJobProjectionRecord)
            .where(
                VideoJobProjectionRecord.project_id == project_id,
                VideoJobProjectionRecord.external_job_id == job_id,
            )
            .with_for_update()
        )
        if job is None:
            raise CompetitionVerticalSliceError("clicked video job disappeared")
        payload = dict(job.payload)
        replay = payload.get("competitionVerticalSlice")
        if replay is not None and replay != envelope:
            raise CompetitionVerticalSliceError("delivery envelope changed on replay")
        operation = session.scalar(
            select(OperationRunRecord)
            .where(
                OperationRunRecord.id == operation_run_id,
                OperationRunRecord.project_id == project_id,
            )
            .with_for_update()
        )
        if operation is None:
            raise CompetitionVerticalSliceError("H3 operation disappeared")
        operations = OperationRepository(session)
        state = session.get(OperationAttemptStateRecord, attempt_id)
        if state is None:
            raise CompetitionVerticalSliceError("H3 attempt state disappeared")
        if state.status != "SUCCEEDED":
            operations.compare_and_set_attempt_state(
                attempt_id=attempt_id,
                project_id=project_id,
                expected_state_version=state.state_version,
                status="SUCCEEDED",
                stage="COMMITTED",
                event_type="SUCCEEDED",
                metrics={
                    "requested_frame_count": 73,
                    "requested_fps": 24,
                    "actual_frame_count": actual_media[1],
                    "actual_fps": actual_media[2],
                    "actual_duration_seconds": actual_media[0],
                    "byte_size": byte_size,
                },
            )
        if operation.accepted_attempt_id is None:
            operations.accept_attempt(
                operation_run_id=operation.id,
                attempt_id=attempt_id,
                project_id=project_id,
                expected_state_version=operation.state_version,
            )
        elif operation.accepted_attempt_id != attempt_id:
            raise CompetitionVerticalSliceError("H3 operation accepted another attempt")
        delivery_payload = {
            "schema_version": "amd.competition-vertical-slice-delivery.v1",
            "workflow_run_id": str(operation.workflow_run_id),
            "video_job_projection_id": str(job.id),
            "job_id": job_id,
            "envelope": envelope,
        }
        delivery_digest = canonical_json_digest(delivery_payload)
        delivery_id = uuid5(
            NAMESPACE_URL,
            f"amd-competition-delivery:{project_id}:{job.id}:{delivery_digest}",
        )
        delivery = session.get(DeliveryRevisionRecord, delivery_id)
        if delivery is None:
            revision = session.scalar(
                select(func.max(DeliveryRevisionRecord.revision)).where(
                    DeliveryRevisionRecord.project_id == project_id
                )
            ) or 0
            delivery = DeliveryRevisionRecord(
                id=delivery_id,
                project_id=project_id,
                revision=revision + 1,
                digest=delivery_digest,
                created_by_actor="amd.competition-vertical-slice",
                payload=delivery_payload,
            )
            session.add(delivery)
            session.flush()
        elif (
            delivery.project_id != project_id
            or delivery.digest != delivery_digest
            or delivery.payload != delivery_payload
            or delivery.created_by_actor != "amd.competition-vertical-slice"
        ):
            raise CompetitionVerticalSliceError("delivery authority replay conflicts")
        payload["competitionVerticalSlice"] = envelope
        payload["competitionVerticalSliceDeliveryId"] = str(delivery_id)
        payload["competitionVerticalSliceDeliveryDigest"] = delivery_digest
        job.payload = payload
        job.status = "succeeded"
        session.flush()
    return envelope


__all__ = [
    "CompetitionVerticalSliceError",
    "build_competition_vertical_slice_envelope",
    "publish_competition_vertical_slice",
]
