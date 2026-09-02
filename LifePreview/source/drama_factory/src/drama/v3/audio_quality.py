"""Fail-closed technical quality checks for immutable narration WAV takes."""

from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass, fields
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True, slots=True)
class AudioQualityPolicy:
    expected_sample_rate_hz: int = 24_000
    expected_channels: int = 1
    expected_pcm_sample_width_bytes: int = 2
    minimum_duration_seconds: float = 0.05
    maximum_duration_seconds: float = 300.0
    duration_variance_ratio: float = 0.25
    duration_tolerance_seconds: float = 0.20
    silence_amplitude_ratio: float = 0.01
    maximum_silence_ratio: float = 0.90
    clipping_amplitude_ratio: float = 0.999
    maximum_clipping_ratio: float = 0.005
    maximum_edge_silence_seconds: float = 0.35
    truncation_terminal_amplitude_ratio: float = 0.15
    maximum_file_bytes: int = 100 * 1024 * 1024

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{item.name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{item.name} must be finite")
        if self.expected_sample_rate_hz <= 0:
            raise ValueError("expected sample rate must be positive")
        if self.expected_channels <= 0:
            raise ValueError("expected channels must be positive")
        if self.expected_pcm_sample_width_bytes != 2:
            raise ValueError("only 16-bit PCM output is supported")
        if not 0 < self.minimum_duration_seconds < self.maximum_duration_seconds:
            raise ValueError("duration policy is invalid")
        if self.duration_variance_ratio < 0 or self.duration_tolerance_seconds < 0:
            raise ValueError("duration tolerances must be non-negative")
        for name in (
            "silence_amplitude_ratio",
            "maximum_silence_ratio",
            "clipping_amplitude_ratio",
            "maximum_clipping_ratio",
            "truncation_terminal_amplitude_ratio",
        ):
            value = float(getattr(self, name))
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if self.maximum_edge_silence_seconds < 0 or self.maximum_file_bytes <= 44:
            raise ValueError("audio size policy is invalid")


class AudioQualityResult(_FrozenModel):
    accepted: bool
    defect_codes: tuple[str, ...]
    sample_rate_hz: int = Field(ge=0)
    channels: int = Field(ge=0)
    pcm_sample_width_bytes: int = Field(ge=0)
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    peak_amplitude: float = Field(ge=0, le=1, allow_inf_nan=False)
    clipping_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    silence_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    leading_silence_seconds: float = Field(ge=0, allow_inf_nan=False)
    trailing_silence_seconds: float = Field(ge=0, allow_inf_nan=False)


def _rejected(*codes: str) -> AudioQualityResult:
    return AudioQualityResult(
        accepted=False,
        defect_codes=tuple(dict.fromkeys(codes)),
        sample_rate_hz=0,
        channels=0,
        pcm_sample_width_bytes=0,
        duration_seconds=0.0,
        peak_amplitude=0.0,
        clipping_ratio=0.0,
        silence_ratio=1.0,
        leading_silence_seconds=0.0,
        trailing_silence_seconds=0.0,
    )


class AudioQualityAnalyzer:
    def __init__(self, policy: AudioQualityPolicy | None = None) -> None:
        self.policy = policy or AudioQualityPolicy()

    def inspect(
        self,
        path: str | Path,
        *,
        planned_duration_seconds: float | None = None,
    ) -> AudioQualityResult:
        if planned_duration_seconds is not None and (
            isinstance(planned_duration_seconds, bool)
            or not isinstance(planned_duration_seconds, (int, float))
            or not math.isfinite(float(planned_duration_seconds))
            or planned_duration_seconds <= 0
        ):
            raise ValueError("planned duration must be finite and positive")

        source = Path(path)
        try:
            size = source.stat().st_size
        except OSError:
            return _rejected("invalid_wav")
        if size <= 44 or size > self.policy.maximum_file_bytes:
            return _rejected("invalid_wav")

        try:
            with wave.open(str(source), "rb") as handle:
                channels = handle.getnchannels()
                sample_width = handle.getsampwidth()
                sample_rate = handle.getframerate()
                frame_count = handle.getnframes()
                compression = handle.getcomptype()
                frames_payload = handle.readframes(frame_count)
        except (EOFError, OSError, wave.Error, struct.error):
            return _rejected("invalid_wav")

        if (
            channels <= 0
            or sample_rate <= 0
            or frame_count <= 0
            or compression != "NONE"
            or not frames_payload
        ):
            return _rejected("invalid_wav")

        duration = frame_count / sample_rate
        if not math.isfinite(duration) or duration <= 0:
            return _rejected("invalid_wav")

        defects: list[str] = []
        if sample_rate != self.policy.expected_sample_rate_hz:
            defects.append("sample_rate_mismatch")
        if channels != self.policy.expected_channels:
            defects.append("channel_mismatch")
        if sample_width != self.policy.expected_pcm_sample_width_bytes:
            defects.append("pcm_format_mismatch")
        if duration < self.policy.minimum_duration_seconds:
            defects.append("duration_too_short")
        if duration > self.policy.maximum_duration_seconds:
            defects.append("duration_too_long")
        if planned_duration_seconds is not None:
            tolerance = max(
                self.policy.duration_tolerance_seconds,
                float(planned_duration_seconds) * self.policy.duration_variance_ratio,
            )
            if abs(duration - float(planned_duration_seconds)) > tolerance:
                defects.append("duration_variance")

        samples = self._decode_samples(frames_payload, sample_width)
        if samples is None or not samples:
            return _rejected(*defects, "invalid_wav")
        frame_peaks = [
            max(abs(item) for item in samples[index : index + channels])
            for index in range(0, len(samples), channels)
            if len(samples[index : index + channels]) == channels
        ]
        if len(frame_peaks) != frame_count:
            return _rejected(*defects, "invalid_wav")

        full_scale = float(2 ** (sample_width * 8 - 1))
        silence_level = full_scale * self.policy.silence_amplitude_ratio
        clipping_level = full_scale * self.policy.clipping_amplitude_ratio
        peak = max(frame_peaks) / full_scale
        silent = sum(value <= silence_level for value in frame_peaks)
        clipped = sum(value >= clipping_level for value in frame_peaks)
        silence_ratio = silent / frame_count
        clipping_ratio = clipped / frame_count
        leading_frames = 0
        for value in frame_peaks:
            if value > silence_level:
                break
            leading_frames += 1
        trailing_frames = 0
        for value in reversed(frame_peaks):
            if value > silence_level:
                break
            trailing_frames += 1
        leading_silence = leading_frames / sample_rate
        trailing_silence = trailing_frames / sample_rate

        if peak <= self.policy.silence_amplitude_ratio:
            defects.append("all_silence")
        elif silence_ratio > self.policy.maximum_silence_ratio:
            defects.append("excessive_silence")
        if clipping_ratio > self.policy.maximum_clipping_ratio:
            defects.append("clipping")
        if leading_silence > self.policy.maximum_edge_silence_seconds:
            defects.append("leading_silence")
        if trailing_silence > self.policy.maximum_edge_silence_seconds:
            defects.append("trailing_silence")
        if (
            peak > self.policy.silence_amplitude_ratio
            and frame_peaks[-1]
            >= full_scale * self.policy.truncation_terminal_amplitude_ratio
        ):
            defects.append("possible_truncation")

        return AudioQualityResult(
            accepted=not defects,
            defect_codes=tuple(dict.fromkeys(defects)),
            sample_rate_hz=sample_rate,
            channels=channels,
            pcm_sample_width_bytes=sample_width,
            duration_seconds=duration,
            peak_amplitude=min(1.0, peak),
            clipping_ratio=clipping_ratio,
            silence_ratio=silence_ratio,
            leading_silence_seconds=leading_silence,
            trailing_silence_seconds=trailing_silence,
        )

    @staticmethod
    def _decode_samples(payload: bytes, sample_width: int) -> list[int] | None:
        if sample_width == 2:
            if len(payload) % 2:
                return None
            return list(struct.unpack(f"<{len(payload) // 2}h", payload))
        if sample_width == 1:
            return [(item - 128) * 256 for item in payload]
        return None


__all__ = ["AudioQualityAnalyzer", "AudioQualityPolicy", "AudioQualityResult"]
