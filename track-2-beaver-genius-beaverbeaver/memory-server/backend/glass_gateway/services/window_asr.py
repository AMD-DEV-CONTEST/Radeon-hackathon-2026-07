from __future__ import annotations

import re
import time
import uuid
from typing import Any, Protocol


class SegmentTranscriber(Protocol):
    async def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str: ...


class WindowASRProcessor:
    """Run ASR after an independent speech-presence decision.

    Evaluation mode can transcribe frozen VAD segments. Production mode keeps
    those segments for audit while transcribing the complete window and an
    overlapping tail guard. An empty ASR response never changes the original
    speech-presence decision.
    """

    def __init__(
        self,
        transcriber: SegmentTranscriber,
        *,
        method_version: str = "m1-presence-segments-v1",
        max_attempts: int = 2,
        transcribe_full_window: bool = False,
        tail_guard_ms: int = 0,
    ) -> None:
        self.transcriber = transcriber
        self.method_version = method_version
        self.max_attempts = max(1, int(max_attempts))
        self.transcribe_full_window = bool(transcribe_full_window)
        self.tail_guard_ms = max(0, int(tail_guard_ms))

    async def process(
        self,
        *,
        window_id: str,
        pcm_bytes: bytes,
        sample_rate: int,
        speech_segments: list[dict[str, Any]],
        audio_evidence_refs: list[str],
        presence_run_id: str | None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        output_segments: list[dict[str, Any]] = []
        warnings: list[str] = []
        errors: list[dict[str, Any]] = []
        presence_segments = [dict(item) for item in speech_segments]
        duration_ms = round(len(pcm_bytes) / 2 / sample_rate * 1000)
        processing_segments = presence_segments
        if self.transcribe_full_window:
            confidence = max(
                (float(item.get("confidence") or 0.0) for item in presence_segments),
                default=0.0,
            )
            processing_segments = [
                {
                    "start_ms": 0,
                    "end_ms": duration_ms,
                    "confidence": confidence,
                    "purpose": "full_window",
                }
            ]
            if 0 < self.tail_guard_ms < duration_ms:
                processing_segments.append(
                    {
                        "start_ms": duration_ms - self.tail_guard_ms,
                        "end_ms": duration_ms,
                        "confidence": confidence,
                        "purpose": "tail_guard",
                    }
                )

        for index, source in enumerate(processing_segments):
            start_ms, end_ms, body = self._slice_segment(
                pcm_bytes,
                sample_rate,
                source,
            )
            if not body:
                warnings.append(f"segment_{index}_empty_audio")
                output_segments.append(
                    self._segment_result(
                        source,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        status="speech_unrecognized",
                        text="",
                        latency_ms=0,
                    )
                )
                continue

            segment_started = time.perf_counter()
            text = ""
            error: Exception | None = None
            attempts = 0
            for attempts in range(1, self.max_attempts + 1):
                try:
                    text = (await self.transcriber.transcribe(body, sample_rate)).strip()
                except Exception as exc:
                    error = exc
                    if attempts < self.max_attempts:
                        continue
                else:
                    error = None
                    if attempts > 1:
                        warnings.append(f"segment_{index}_retry_succeeded")
                    break

            latency_ms = round((time.perf_counter() - segment_started) * 1000)
            if error is not None:
                detail = {
                    "segment_index": index,
                    "type": type(error).__name__,
                    "message": str(error),
                    "attempts": attempts,
                }
                errors.append(detail)
                output_segments.append(
                    self._segment_result(
                        source,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        status="asr_failed",
                        text="",
                        latency_ms=latency_ms,
                        error=detail,
                    )
                )
                continue

            purpose = str(source.get("purpose") or "presence_segment")
            output_segments.append(
                self._segment_result(
                    source,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    status=(
                        "completed"
                        if text
                        else "tail_unrecognized"
                        if purpose == "tail_guard"
                        else "speech_unrecognized"
                    ),
                    text=text,
                    latency_ms=latency_ms,
                )
            )

        recognized: list[str] = []
        for item in output_segments:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            if item.get("purpose") == "tail_guard" and any(
                _same_or_contained_text(text, previous) for previous in recognized
            ):
                item["status"] = "tail_duplicate"
                warnings.append("tail_guard_duplicate_suppressed")
                continue
            recognized.append(text)
        primary_segments = [
            item for item in output_segments if item.get("purpose") != "tail_guard"
        ]
        failed_count = sum(item.get("status") == "asr_failed" for item in primary_segments)
        unrecognized_count = sum(
            item.get("status") == "speech_unrecognized" for item in primary_segments
        )
        if recognized and not failed_count and not unrecognized_count:
            status = "completed"
        elif recognized:
            status = "partial"
        elif failed_count:
            status = "asr_failed"
        else:
            status = "speech_unrecognized"

        return {
            "asr_run_id": f"asr-{uuid.uuid4().hex}",
            "window_id": window_id,
            "status": status,
            "provider": str(getattr(self.transcriber, "provider_name", type(self.transcriber).__name__)),
            "model": str(getattr(self.transcriber, "model_name", "unknown")),
            "method_version": self.method_version,
            "language": str(getattr(self.transcriber, "language", "zh")),
            "transcript": "\n".join(recognized),
            "segments": output_segments,
            "input_segments": processing_segments,
            "presence_segments": presence_segments,
            "transcription_mode": (
                "full_window_vad_gated"
                if self.transcribe_full_window
                else "presence_segments"
            ),
            "timing_precision": (
                "window_plus_tail_guard"
                if self.transcribe_full_window
                else "presence_segment"
            ),
            "tail_guard_ms": (
                self.tail_guard_ms if self.transcribe_full_window else 0
            ),
            "audio_duration_ms": duration_ms,
            "audio_evidence_refs": audio_evidence_refs,
            "presence_run_id": presence_run_id,
            "warnings": warnings,
            "errors": errors,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }

    @staticmethod
    def not_requested(
        *,
        window_id: str,
        reason: str,
        audio_evidence_refs: list[str],
        presence_run_id: str | None,
        speech_segments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "asr_run_id": f"asr-{uuid.uuid4().hex}",
            "window_id": window_id,
            "status": "not_requested",
            "reason": reason,
            "provider": "not_requested",
            "model": "not_requested",
            "method_version": "m1-presence-segments-v1",
            "language": "zh",
            "transcript": "",
            "segments": [],
            "input_segments": speech_segments or [],
            "audio_evidence_refs": audio_evidence_refs,
            "presence_run_id": presence_run_id,
            "warnings": [],
            "errors": [],
            "latency_ms": 0,
        }

    @staticmethod
    def unavailable(
        *,
        window_id: str,
        audio_evidence_refs: list[str],
        presence_run_id: str | None,
        speech_segments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "asr_run_id": f"asr-{uuid.uuid4().hex}",
            "window_id": window_id,
            "status": "asr_failed",
            "reason": "asr_not_configured",
            "provider": "unavailable",
            "model": "unavailable",
            "method_version": "m1-presence-segments-v1",
            "language": "zh",
            "transcript": "",
            "segments": [],
            "input_segments": speech_segments,
            "audio_evidence_refs": audio_evidence_refs,
            "presence_run_id": presence_run_id,
            "warnings": [],
            "errors": [
                {
                    "type": "RuntimeError",
                    "message": "ASR transcriber is not configured",
                }
            ],
            "latency_ms": 0,
        }

    @staticmethod
    def _slice_segment(
        pcm_bytes: bytes,
        sample_rate: int,
        segment: dict[str, Any],
    ) -> tuple[int, int, bytes]:
        start_ms = max(0, int(segment.get("start_ms") or 0))
        end_ms = max(start_ms, int(segment.get("end_ms") or start_ms))
        bytes_per_ms = sample_rate * 2 / 1000
        start_byte = int(start_ms * bytes_per_ms) // 2 * 2
        end_byte = int(end_ms * bytes_per_ms) // 2 * 2
        return start_ms, end_ms, pcm_bytes[start_byte:end_byte]

    @staticmethod
    def _segment_result(
        source: dict[str, Any],
        *,
        start_ms: int,
        end_ms: int,
        status: str,
        text: str,
        latency_ms: int,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": text,
            "confidence": None,
            "status": status,
            "latency_ms": latency_ms,
        }
        if source.get("confidence") is not None:
            result["speech_presence_confidence"] = source["confidence"]
        if source.get("purpose"):
            result["purpose"] = source["purpose"]
        if error is not None:
            result["error"] = error
        return result


def _same_or_contained_text(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        return re.sub(r"[^\w\u3400-\u9fff]+", "", value.casefold())

    left_key = normalize(left)
    right_key = normalize(right)
    if not left_key or not right_key:
        return False
    return left_key in right_key
