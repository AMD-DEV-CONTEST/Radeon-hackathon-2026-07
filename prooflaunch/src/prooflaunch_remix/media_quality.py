from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image

from .mission import MissionError


def _pixels(image: Image.Image):
    return (
        image.get_flattened_data()
        if hasattr(image, "get_flattened_data")
        else image.getdata()
    )


def _nearest_rank(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise MissionError("percentile requires at least one value")
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _product_box(
    frame_size: tuple[int, int],
    normalized_box: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    width, height = frame_size
    x1 = round(normalized_box[0] * width)
    y1 = round(normalized_box[1] * height)
    x2 = round(normalized_box[2] * width)
    y2 = round(normalized_box[3] * height)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise MissionError("product box is outside the decoded video canvas")
    return x1, y1, x2, y2


def _masked_mae(
    actual: Image.Image,
    expected: Image.Image,
    mask: Image.Image,
) -> float:
    actual_pixels = _pixels(actual.convert("RGB"))
    expected_pixels = _pixels(expected.convert("RGB"))
    mask_pixels = _pixels(mask.convert("L"))
    error = 0
    channel_count = 0
    for observed, reference, opacity in zip(
        actual_pixels, expected_pixels, mask_pixels
    ):
        if opacity != 255:
            continue
        error += sum(abs(a - b) for a, b in zip(observed, reference))
        channel_count += 3
    if channel_count == 0:
        raise MissionError("product layer has no opaque identity pixels")
    return error / (channel_count * 255)


@dataclass(frozen=True)
class EncodedVideoIdentityReport:
    passed: bool
    decoded_frame_count: int
    expected_frame_count: int
    frame_coverage: float
    mean_normalized_mae: float
    p95_normalized_mae: float
    max_normalized_mae: float
    frame_normalized_mae: tuple[float, ...]
    product_box: tuple[int, int, int, int]
    codec_tolerance: float
    minimum_frame_coverage: float
    schema: str = "ProofLaunchEncodedVideoIdentityReportV1"

    def to_dict(self) -> dict:
        return asdict(self)


class EncodedVideoIdentityGate:
    """Audits the final decoded MP4, not only the lossless pre-encode frames."""

    def __init__(
        self,
        *,
        decoder: Callable[[str | Path], Iterable[Image.Image]] | None = None,
        codec_tolerance: float = 0.04,
        minimum_frame_coverage: float = 0.95,
    ) -> None:
        if not 0 <= codec_tolerance <= 1:
            raise MissionError("codec tolerance must be between zero and one")
        if not 0 < minimum_frame_coverage <= 1:
            raise MissionError("frame coverage must be between zero and one")
        self.decoder = decoder or self._decode_with_pyav
        self.codec_tolerance = codec_tolerance
        self.minimum_frame_coverage = minimum_frame_coverage

    @staticmethod
    def _decode_with_pyav(path: str | Path) -> tuple[Image.Image, ...]:
        import av

        frames: list[Image.Image] = []
        with av.open(str(path)) as container:
            for frame in container.decode(video=0):
                frames.append(frame.to_image().convert("RGB"))
        return tuple(frames)

    def audit(
        self,
        *,
        video_path: str | Path,
        product_layer: Image.Image,
        normalized_box: tuple[float, float, float, float],
        expected_frame_count: int,
    ) -> EncodedVideoIdentityReport:
        if expected_frame_count <= 0:
            raise MissionError("expected frame count must be positive")
        frames = tuple(frame.convert("RGB") for frame in self.decoder(video_path))
        if not frames:
            raise MissionError("encoded video decoder returned no frames")
        size = frames[0].size
        if any(frame.size != size for frame in frames):
            raise MissionError("decoded video frames have inconsistent dimensions")
        box = _product_box(size, normalized_box)
        expected = product_layer.convert("RGBA").resize(
            (box[2] - box[0], box[3] - box[1]),
            Image.Resampling.LANCZOS,
        )
        mask = expected.getchannel("A")
        frame_errors = tuple(
            _masked_mae(frame.crop(box), expected, mask) for frame in frames
        )
        coverage = min(1.0, len(frames) / expected_frame_count)
        mean_error = sum(frame_errors) / len(frame_errors)
        p95_error = _nearest_rank(frame_errors, 0.95)
        max_error = max(frame_errors)
        return EncodedVideoIdentityReport(
            passed=(
                coverage >= self.minimum_frame_coverage
                and p95_error <= self.codec_tolerance
            ),
            decoded_frame_count=len(frames),
            expected_frame_count=expected_frame_count,
            frame_coverage=coverage,
            mean_normalized_mae=mean_error,
            p95_normalized_mae=p95_error,
            max_normalized_mae=max_error,
            frame_normalized_mae=frame_errors,
            product_box=box,
            codec_tolerance=self.codec_tolerance,
            minimum_frame_coverage=self.minimum_frame_coverage,
        )


@dataclass(frozen=True)
class SemanticEvent:
    label: str
    start_seconds: float
    end_seconds: float
    confidence: float
    locator: str

    def __post_init__(self) -> None:
        if not self.label.strip() or not self.locator.strip():
            raise MissionError("semantic event requires a label and locator")
        if self.start_seconds < 0 or self.end_seconds < self.start_seconds:
            raise MissionError("semantic event interval is invalid")
        if not 0 <= self.confidence <= 1:
            raise MissionError("semantic event confidence must be between zero and one")

    @property
    def midpoint(self) -> float:
        return (self.start_seconds + self.end_seconds) / 2

    @property
    def normalized_label(self) -> str:
        return " ".join(re.findall(r"[\w]+", self.label.casefold()))


@dataclass(frozen=True)
class EventAlignment:
    label: str
    audio_locator: str
    video_locator: str
    midpoint_delta_seconds: float


@dataclass(frozen=True)
class AudioVideoAlignmentReport:
    passed: bool
    matched_event_count: int
    audio_event_count: int
    video_event_count: int
    event_coverage: float
    p95_midpoint_delta_seconds: float | None
    duration_delta_seconds: float
    tolerance_seconds: float
    duration_tolerance_seconds: float
    minimum_event_coverage: float
    alignments: tuple[EventAlignment, ...]
    missing_audio_labels: tuple[str, ...]
    missing_video_labels: tuple[str, ...]
    schema: str = "ProofLaunchAudioVideoAlignmentReportV1"

    def to_dict(self) -> dict:
        return asdict(self)


class AudioVideoAlignmentGate:
    """Matches timestamped semantic events and rejects structural A/V drift."""

    def __init__(
        self,
        *,
        tolerance_seconds: float = 0.50,
        duration_tolerance_seconds: float = 0.25,
        minimum_event_coverage: float = 0.90,
        minimum_confidence: float = 0.50,
    ) -> None:
        if tolerance_seconds < 0 or duration_tolerance_seconds < 0:
            raise MissionError("alignment tolerances cannot be negative")
        if not 0 < minimum_event_coverage <= 1:
            raise MissionError("event coverage must be between zero and one")
        if not 0 <= minimum_confidence <= 1:
            raise MissionError("minimum confidence must be between zero and one")
        self.tolerance_seconds = tolerance_seconds
        self.duration_tolerance_seconds = duration_tolerance_seconds
        self.minimum_event_coverage = minimum_event_coverage
        self.minimum_confidence = minimum_confidence

    def audit(
        self,
        *,
        audio_events: Iterable[SemanticEvent],
        video_events: Iterable[SemanticEvent],
        audio_duration_seconds: float,
        video_duration_seconds: float,
    ) -> AudioVideoAlignmentReport:
        if audio_duration_seconds <= 0 or video_duration_seconds <= 0:
            raise MissionError("audio and video durations must be positive")
        audio = tuple(
            item for item in audio_events if item.confidence >= self.minimum_confidence
        )
        video = tuple(
            item for item in video_events if item.confidence >= self.minimum_confidence
        )
        if not audio or not video:
            raise MissionError("alignment gate requires confident audio and video events")
        unused_video = set(range(len(video)))
        alignments: list[EventAlignment] = []
        missing_audio: list[str] = []
        for audio_event in audio:
            choices = [
                index
                for index in unused_video
                if video[index].normalized_label == audio_event.normalized_label
            ]
            if not choices:
                missing_audio.append(audio_event.label)
                continue
            selected = min(
                choices,
                key=lambda index: abs(video[index].midpoint - audio_event.midpoint),
            )
            unused_video.remove(selected)
            video_event = video[selected]
            alignments.append(
                EventAlignment(
                    label=audio_event.label,
                    audio_locator=audio_event.locator,
                    video_locator=video_event.locator,
                    midpoint_delta_seconds=abs(
                        video_event.midpoint - audio_event.midpoint
                    ),
                )
            )
        denominator = max(len(audio), len(video))
        coverage = len(alignments) / denominator
        deltas = tuple(item.midpoint_delta_seconds for item in alignments)
        p95 = _nearest_rank(deltas, 0.95) if deltas else None
        duration_delta = abs(audio_duration_seconds - video_duration_seconds)
        missing_video = tuple(video[index].label for index in sorted(unused_video))
        passed = (
            coverage >= self.minimum_event_coverage
            and p95 is not None
            and p95 <= self.tolerance_seconds
            and duration_delta <= self.duration_tolerance_seconds
        )
        return AudioVideoAlignmentReport(
            passed=passed,
            matched_event_count=len(alignments),
            audio_event_count=len(audio),
            video_event_count=len(video),
            event_coverage=coverage,
            p95_midpoint_delta_seconds=p95,
            duration_delta_seconds=duration_delta,
            tolerance_seconds=self.tolerance_seconds,
            duration_tolerance_seconds=self.duration_tolerance_seconds,
            minimum_event_coverage=self.minimum_event_coverage,
            alignments=tuple(alignments),
            missing_audio_labels=tuple(missing_audio),
            missing_video_labels=missing_video,
        )
