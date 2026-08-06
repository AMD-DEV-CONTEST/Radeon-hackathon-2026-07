from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from shared_contracts import ArtifactRef, VideoResolution

from .domain import (
    FACTORY_QC_DIMENSION_IDS,
    FactoryQCEvaluation,
    FactoryQCEvidenceSpan,
    FactoryQCScore,
    FactoryQCVerdict,
)


class FactoryQCError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MediaProbe:
    width: int
    height: int
    duration_seconds: float
    frame_rate: float
    video_codec: str
    audio_codec: str | None


def _fraction(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    if "/" not in value:
        return float(value)
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator)


def probe_media(path: Path, *, ffprobe: str = "ffprobe") -> MediaProbe:
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise FactoryQCError("ffprobe could not inspect the media") from exc
    streams = payload.get("streams", [])
    video = next(
        (item for item in streams if item.get("codec_type") == "video"),
        None,
    )
    audio = next(
        (item for item in streams if item.get("codec_type") == "audio"),
        None,
    )
    if not isinstance(video, dict):
        raise FactoryQCError("media does not contain a video stream")
    try:
        duration = float(
            video.get("duration")
            or payload.get("format", {}).get("duration")
        )
        width = int(video["width"])
        height = int(video["height"])
        frame_rate = _fraction(
            video.get("avg_frame_rate") or video.get("r_frame_rate")
        )
        video_codec = str(video["codec_name"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise FactoryQCError("ffprobe returned incomplete media facts") from exc
    if duration <= 0 or width <= 0 or height <= 0 or frame_rate <= 0:
        raise FactoryQCError("media facts are not physically valid")
    return MediaProbe(
        width=width,
        height=height,
        duration_seconds=duration,
        frame_rate=frame_rate,
        video_codec=video_codec,
        audio_codec=None if audio is None else str(audio.get("codec_name")),
    )


class FactoryTechnicalQC:
    """Evidence-honest technical QC; unobserved aesthetic dimensions are N/A."""

    def __init__(
        self,
        *,
        evaluator_model: str = "factory-technical-qc.ffprobe",
        model_version: str = "1",
        prompt_version: str = "factory-qc-technical.v1",
    ) -> None:
        self.evaluator_model = evaluator_model
        self.model_version = model_version
        self.prompt_version = prompt_version

    @staticmethod
    def _score(
        dimension_id: str,
        *,
        score: int | None,
        reason: str,
        na_reason: str | None,
        artifact_ref: ArtifactRef,
        duration_ms: int,
    ) -> FactoryQCScore:
        return FactoryQCScore(
            dimension_id=dimension_id,
            score=score,
            confidence=1.0 if score is not None else None,
            reason=reason,
            na_reason=na_reason,
            evidence=(
                FactoryQCEvidenceSpan(
                    artifact_ref=artifact_ref,
                    start_ms=0,
                    end_ms=duration_ms,
                    note="full media probe",
                ),
            ),
        )

    def evaluate(
        self,
        *,
        subject_type: Literal["visual_take", "delivery_take"],
        subject_id: UUID,
        artifact_ref: ArtifactRef,
        media_path: Path,
        expected_resolution: VideoResolution,
        expected_duration_seconds: float,
        forced_verdict: FactoryQCVerdict | None = None,
        created_at: datetime | None = None,
    ) -> FactoryQCEvaluation:
        probe = probe_media(media_path)
        resolution_ok = (
            probe.width == expected_resolution.width
            and probe.height == expected_resolution.height
        )
        duration_error = abs(
            probe.duration_seconds - expected_duration_seconds
        )
        duration_ok = duration_error <= max(
            0.25,
            expected_duration_seconds * 0.1,
        )
        technical_score = 10 if resolution_ok and duration_ok else 4
        duration_ms = round(probe.duration_seconds * 1000)
        scores: list[FactoryQCScore] = []
        for dimension_id in FACTORY_QC_DIMENSION_IDS:
            if dimension_id == "technical_quality":
                scores.append(
                    self._score(
                        dimension_id,
                        score=technical_score,
                        reason=(
                            f"{probe.video_codec} {probe.width}x{probe.height}, "
                            f"{probe.duration_seconds:.3f}s, "
                            f"{probe.frame_rate:.3f}fps"
                        ),
                        na_reason=None,
                        artifact_ref=artifact_ref,
                        duration_ms=duration_ms,
                    )
                )
            elif (
                dimension_id == "audio_technical_quality"
                and subject_type == "delivery_take"
            ):
                audio_score = 9 if probe.audio_codec else 2
                scores.append(
                    self._score(
                        dimension_id,
                        score=audio_score,
                        reason=(
                            f"audio codec: {probe.audio_codec}"
                            if probe.audio_codec
                            else "final composite has no audio stream"
                        ),
                        na_reason=None,
                        artifact_ref=artifact_ref,
                        duration_ms=duration_ms,
                    )
                )
            else:
                scores.append(
                    self._score(
                        dimension_id,
                        score=None,
                        reason="this deterministic probe cannot observe the dimension",
                        na_reason="requires an audiovisual model or human review",
                        artifact_ref=artifact_ref,
                        duration_ms=duration_ms,
                    )
                )
        verdict = forced_verdict or (
            FactoryQCVerdict.PASS
            if technical_score >= 7
            and (
                subject_type == "visual_take"
                or probe.audio_codec is not None
            )
            else FactoryQCVerdict.FAIL
        )
        return FactoryQCEvaluation(
            evaluation_id=uuid4(),
            subject_type=subject_type,
            subject_id=subject_id,
            evaluator_model=self.evaluator_model,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            evidence_mode="full_video",
            scores=tuple(scores),
            verdict=verdict,
            attempts_exhausted=verdict is FactoryQCVerdict.NEEDS_HUMAN,
            created_at=created_at or datetime.now(timezone.utc),
        )
