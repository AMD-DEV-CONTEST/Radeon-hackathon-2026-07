from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
import hashlib
import time
from typing import Protocol

from glass_gateway.domain.meeting import StoredEvidence
from glass_gateway.schemas.device_protocol import AudioFormat
from glass_gateway.services.capture_clock import BEIJING_TIMEZONE, ServerClockAnchor
from glass_gateway.services.evidence_store import LocalEvidenceStore
from glass_gateway.services.meeting_detector import MeetingDetector
from glass_gateway.services.technical_window import build_technical_window_contract


MAX_AUDIO_SERVER_DRIFT_MS = 10 * 60 * 1000
# Glass camera uploads normally arrive within about one second.  A two-second
# tolerance leaves room for LAN jitter while preventing a delayed audio stream
# rotation from mapping photos into the next 30-second capsule.
MAX_IMAGE_SERVER_DRIFT_MS = 2 * 1000


class MeetingBridge(Protocol):
    async def close_window(
        self,
        *,
        session_id: str,
        user_id: str,
        sender_name: str,
        audio_chunks: list[StoredEvidence],
        images: list[StoredEvidence],
        sample_rate: int,
        image_width: int,
        image_height: int,
        window_metadata: dict | None = None,
    ) -> dict: ...


@dataclass
class CaptureWindow:
    device_id: str
    stream_id: str
    session_prefix: str
    format: AudioFormat
    detector: MeetingDetector
    clock_anchor: ServerClockAnchor
    boot_session_key: str
    current_window_started_at_ms: int
    image_clock_anchor: ServerClockAnchor | None = None
    expected_index: int = 0
    audio_chunks: list[StoredEvidence] = field(default_factory=list)
    images: list[StoredEvidence] = field(default_factory=list)
    image_width: int = 0
    image_height: int = 0
    window_index: int = 0
    audio_gaps: list[dict[str, int]] = field(default_factory=list)
    speech_activity: list[dict[str, int | str]] = field(default_factory=list)
    speech_active_at_window_start: bool = False
    cross_window_images: list[StoredEvidence] = field(default_factory=list)
    pending_audio_chunks: dict[int, tuple[StoredEvidence, bytes]] = field(
        default_factory=dict
    )
    audio_sequence_sha256: dict[int, str] = field(default_factory=dict)
    image_sequence_evidence: dict[tuple[str, int], StoredEvidence] = field(
        default_factory=dict
    )

    @property
    def session_id(self) -> str:
        if self.window_index == 0:
            return self.session_prefix
        return f"{self.session_prefix}-{self.window_index + 1:04d}"


class CaptureManager:
    """Transport-only state for active capture windows.

    This class stores raw evidence and decides when to call the EverOS bridge.
    It does not store or infer extracted memories, commitments, profiles, or
    search results.
    """

    def __init__(
        self,
        *,
        raw_media_root,
        bridge: MeetingBridge,
        user_id: str,
        sender_name: str,
        speech_rms: int = 500,
        start_speech_ms: int = 300,
        end_silence_ms: int = 1000,
        max_window_ms: int = 30000,
        image_late_grace_ms: int = 0,
        image_max_server_drift_ms: int = MAX_IMAGE_SERVER_DRIFT_MS,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.store = LocalEvidenceStore(raw_media_root)
        self.bridge = bridge
        self.user_id = user_id
        self.sender_name = sender_name
        self.speech_rms = speech_rms
        self.start_speech_ms = start_speech_ms
        self.end_silence_ms = end_silence_ms
        self.max_window_ms = max_window_ms
        self.image_late_grace_ms = max(0, image_late_grace_ms)
        self.image_max_server_drift_ms = max(0, image_max_server_drift_ms)
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._windows_by_device: dict[str, CaptureWindow] = {}
        self._windows_by_stream: dict[str, CaptureWindow] = {}
        self._unassigned_images: dict[tuple[str, str], list[StoredEvidence]] = {}
        self._background_window_tasks: set[asyncio.Task] = set()

    def active_stream_info(self, *, device_id: str) -> dict[str, object] | None:
        window = self._windows_by_device.get(device_id)
        if window is None:
            return None
        return {
            "stream_id": window.stream_id,
            "boot_session_key": window.boot_session_key,
            "expected_index": window.expected_index,
            "sample_rate": window.format.sample_rate,
            "channels": window.format.channels,
        }

    def start_stream(
        self,
        *,
        device_id: str,
        stream_id: str,
        started_at_ms: int | None = None,
        device_monotonic_ms: int | None = None,
        server_received_at_ms: int | None = None,
        boot_session_key: str | None = None,
        expected_index: int = 0,
        format: AudioFormat,
    ) -> dict:
        del started_at_ms  # Legacy device wall time is deliberately not authoritative.
        server_anchor_ms = (
            server_received_at_ms if server_received_at_ms is not None else self.now_ms()
        )
        clock_anchor = ServerClockAnchor(
            server_anchor_ms=server_anchor_ms,
            device_monotonic_anchor_ms=device_monotonic_ms,
            timezone_name=BEIJING_TIMEZONE,
        )
        previous = self._windows_by_device.get(device_id)
        if previous is not None:
            self._windows_by_stream.pop(previous.stream_id, None)
        session_prefix = f"{stream_id}-{server_anchor_ms}"
        detector = MeetingDetector(
            sample_rate=format.sample_rate,
            speech_rms=self.speech_rms,
            start_speech_ms=self.start_speech_ms,
            end_silence_ms=self.end_silence_ms,
        )
        window = CaptureWindow(
            device_id=device_id,
            stream_id=stream_id,
            session_prefix=session_prefix,
            format=format,
            detector=detector,
            clock_anchor=clock_anchor,
            boot_session_key=boot_session_key or session_prefix,
            current_window_started_at_ms=server_anchor_ms,
            expected_index=max(0, expected_index),
        )
        self._windows_by_device[device_id] = window
        self._windows_by_stream[stream_id] = window
        unassigned_key = (device_id, window.boot_session_key)
        pending_images = self._unassigned_images.pop(unassigned_key, [])
        if pending_images:
            window.images.extend(
                sorted(
                    pending_images,
                    key=lambda item: (
                        item.captured_at_ms,
                        item.sequence if item.sequence is not None else -1,
                    ),
                )
            )
            for item in pending_images:
                if item.sequence is None:
                    continue
                window.image_sequence_evidence[
                    (item.stream_id or stream_id, item.sequence)
                ] = item
        return {
            "type": "capture.stream.started",
            "stream_id": stream_id,
            "expected_index": window.expected_index,
        }

    async def add_audio_chunk(
        self,
        *,
        device_id: str,
        stream_id: str,
        index: int,
        captured_at_ms: int | None = None,
        device_monotonic_ms: int | None = None,
        server_received_at_ms: int | None = None,
        captured_at_corrected_ms: int | None = None,
        captured_at_device_ms: int | None = None,
        clock_synced: bool | None = None,
        boot_id: str | None = None,
        media_stream_id: str | None = None,
        duration_ms: int = 0,
        clock_anomaly: bool = False,
        clock_deviation_ms: int | None = None,
        pcm: bytes,
        defer_window_processing: bool = False,
    ) -> list[dict]:
        window = self._require_window(device_id, stream_id)
        digest = hashlib.sha256(pcm).hexdigest()
        if index < window.expected_index:
            previous_digest = window.audio_sequence_sha256.get(index)
            if previous_digest is not None and previous_digest != digest:
                raise ValueError(
                    f"audio sequence conflict at index {index}: different content"
                )
            return [
                {
                    "type": "capture.audio.ack",
                    "stream_id": stream_id,
                    "index": index,
                    "expected_index": window.expected_index,
                    "duplicate": True,
                }
            ]
        pending = window.pending_audio_chunks.get(index)
        if pending is not None:
            if pending[0].sha256 != digest:
                raise ValueError(
                    f"audio sequence conflict at index {index}: different content"
                )
            return [
                {
                    "type": "capture.audio.ack",
                    "stream_id": stream_id,
                    "index": index,
                    "expected_index": window.expected_index,
                    "duplicate": True,
                }
            ]
        gap_from = window.expected_index if index > window.expected_index else None

        received_at_ms = (
            server_received_at_ms if server_received_at_ms is not None else self.now_ms()
        )
        if captured_at_corrected_ms is not None:
            capture_time = window.clock_anchor.map(
                device_monotonic_ms=device_monotonic_ms,
                server_received_at_ms=captured_at_corrected_ms,
                max_server_drift_ms=MAX_AUDIO_SERVER_DRIFT_MS,
            )
            capture_time = replace(
                capture_time,
                captured_at_ms=captured_at_corrected_ms,
                server_received_at_ms=received_at_ms,
                source="reliable_media_corrected",
            )
        else:
            del captured_at_ms  # Legacy device wall time is diagnostic only.
            capture_time = window.clock_anchor.map(
                device_monotonic_ms=device_monotonic_ms,
                server_received_at_ms=received_at_ms,
                max_server_drift_ms=MAX_AUDIO_SERVER_DRIFT_MS,
            )
        if (
            captured_at_corrected_ms is None
            and capture_time.source == "server_received_drift_guard"
        ):
            # A reboot, counter reset, or corrupted ESP sequence must not leave
            # the rest of this boot mapped hours into the future. Re-anchor the
            # audio clock to authoritative server time and continue in-place.
            window.clock_anchor = ServerClockAnchor(
                server_anchor_ms=received_at_ms,
                device_monotonic_anchor_ms=device_monotonic_ms,
                timezone_name=BEIJING_TIMEZONE,
            )
            capture_time = replace(
                window.clock_anchor.map(
                    device_monotonic_ms=device_monotonic_ms,
                    server_received_at_ms=received_at_ms,
                    max_server_drift_ms=MAX_AUDIO_SERVER_DRIFT_MS,
                ),
                source="server_received_drift_reanchor",
            )
            if not window.audio_chunks and window.current_window_started_at_ms > received_at_ms:
                window.current_window_started_at_ms = received_at_ms
        evidence = await asyncio.to_thread(
            self.store.write_audio_chunk,
            self.user_id,
            stream_id,
            index,
            capture_time.captured_at_ms,
            pcm,
            device_monotonic_ms=capture_time.device_monotonic_ms,
            server_received_at_ms=capture_time.server_received_at_ms,
            server_anchor_ms=capture_time.server_anchor_ms,
            device_monotonic_anchor_ms=capture_time.device_monotonic_anchor_ms,
            timezone_name=capture_time.timezone_name,
            capture_time_source=capture_time.source,
            device_id=device_id,
            boot_id=boot_id,
            media_stream_id=media_stream_id,
            captured_at_device_ms=captured_at_device_ms,
            clock_synced=clock_synced,
            duration_ms=duration_ms,
            clock_anomaly=clock_anomaly,
            clock_deviation_ms=clock_deviation_ms,
        )
        window.pending_audio_chunks[index] = (evidence, pcm)
        drained: list[tuple[StoredEvidence, bytes]] = []
        while window.expected_index in window.pending_audio_chunks:
            next_index = window.expected_index
            next_evidence, next_pcm = window.pending_audio_chunks.pop(next_index)
            window.audio_chunks.append(next_evidence)
            window.audio_sequence_sha256[next_index] = next_evidence.sha256
            window.expected_index += 1
            drained.append((next_evidence, next_pcm))
            for event in window.detector.ingest(next_evidence.captured_at_ms, next_pcm):
                window.speech_activity.append(
                    {"kind": event.kind, "at_ms": event.at_ms}
                )
        self._refresh_audio_gaps(window)
        responses = [
            {
                "type": "capture.audio.ack",
                "stream_id": stream_id,
                "index": index,
                "expected_index": window.expected_index,
                "duplicate": False,
                "gap_from": gap_from,
            }
        ]
        if drained and window.audio_chunks and self._window_reached_max_duration(
            window,
            drained[-1][0].captured_at_ms,
        ):
            if defer_window_processing and len(drained) == 1:
                task = asyncio.create_task(
                    self._close_window(
                        window,
                        reason="capsule_window",
                        freeze_before_grace=True,
                    )
                )
                self._background_window_tasks.add(task)
                task.add_done_callback(self._background_window_tasks.discard)
                responses.append(
                    {
                        "type": "capture.window.processing",
                        "stream_id": stream_id,
                        "session_id": window.session_id,
                        "reason": "capsule_window",
                    }
                )
            else:
                responses.append(await self._close_window(window, reason="capsule_window"))
        return responses

    async def end_stream(
        self,
        *,
        device_id: str,
        stream_id: str,
        ended_at_ms: int,
        device_monotonic_ms: int | None = None,
        server_received_at_ms: int | None = None,
        reason: str,
    ) -> list[dict]:
        window = self._require_window(device_id, stream_id)
        del ended_at_ms  # Legacy device wall time is deliberately not authoritative.
        received_at_ms = (
            server_received_at_ms if server_received_at_ms is not None else self.now_ms()
        )
        ended = window.clock_anchor.map(
            device_monotonic_ms=device_monotonic_ms,
            server_received_at_ms=received_at_ms,
            max_server_drift_ms=MAX_AUDIO_SERVER_DRIFT_MS,
        )
        responses: list[dict] = [
            {
                "type": "capture.stream.ended",
                "stream_id": stream_id,
                "ended_at_ms": ended.captured_at_ms,
                "reason": reason,
            }
        ]
        pending_missing_ranges = list(window.audio_gaps)
        if window.audio_chunks:
            responses.append(await self._close_window(window, reason=reason))
        # A transport boundary is not a semantic memory boundary. Rotation,
        # reconnects, power changes, and capture stops must leave the active
        # event queue open so a later stream can continue the same experience.
        # Semantic boundary detection or the explicit memory flush endpoint is
        # responsible for sealing the event and creating an EverOS Episode.
        if window.pending_audio_chunks:
            responses.append(
                {
                    "type": "capture.stream.awaiting_missing",
                    "stream_id": stream_id,
                    "expected_index": window.expected_index,
                    "missing_ranges": pending_missing_ranges,
                }
            )
        else:
            self._windows_by_device.pop(device_id, None)
            self._windows_by_stream.pop(stream_id, None)
        return responses

    async def store_image(
        self,
        *,
        device_id: str,
        stream_id: str,
        index: int,
        captured_at_ms: int | None = None,
        device_monotonic_ms: int | None = None,
        server_received_at_ms: int | None = None,
        captured_at_corrected_ms: int | None = None,
        captured_at_device_ms: int | None = None,
        clock_synced: bool | None = None,
        boot_id: str | None = None,
        media_stream_id: str | None = None,
        duration_ms: int = 0,
        clock_anomaly: bool = False,
        clock_deviation_ms: int | None = None,
        suffix: str,
        body: bytes,
        width: int | None,
        height: int | None,
    ) -> StoredEvidence:
        received_at_ms = (
            server_received_at_ms if server_received_at_ms is not None else self.now_ms()
        )
        window = self._windows_by_stream.get(stream_id)
        if captured_at_corrected_ms is not None:
            anchor = window.clock_anchor if window and window.device_id == device_id else ServerClockAnchor(
                server_anchor_ms=captured_at_corrected_ms,
                device_monotonic_anchor_ms=device_monotonic_ms,
                timezone_name=BEIJING_TIMEZONE,
            )
            capture_time = replace(
                anchor.map(
                    device_monotonic_ms=device_monotonic_ms,
                    server_received_at_ms=captured_at_corrected_ms,
                    max_server_drift_ms=self.image_max_server_drift_ms,
                ),
                captured_at_ms=captured_at_corrected_ms,
                server_received_at_ms=received_at_ms,
                source="reliable_media_corrected",
            )
        elif window and window.device_id == device_id:
            del captured_at_ms  # Legacy device wall time is diagnostic only.
            image_anchor = window.image_clock_anchor or window.clock_anchor
            capture_time = image_anchor.map(
                device_monotonic_ms=device_monotonic_ms,
                server_received_at_ms=received_at_ms,
                max_server_drift_ms=self.image_max_server_drift_ms,
            )
            if capture_time.source == "server_received_drift_guard":
                # Audio and camera tasks on some ESP builds expose monotonic
                # counters with different origins. Anchor the camera once to
                # the latest audio point so both media types share a window,
                # then preserve camera-relative timing for later frames.
                reference_ms = (
                    window.audio_chunks[-1].captured_at_ms
                    if window.audio_chunks
                    else max(received_at_ms, window.current_window_started_at_ms)
                )
                window.image_clock_anchor = ServerClockAnchor(
                    server_anchor_ms=reference_ms,
                    device_monotonic_anchor_ms=device_monotonic_ms,
                    timezone_name=BEIJING_TIMEZONE,
                )
                capture_time = replace(
                    window.image_clock_anchor.map(
                        device_monotonic_ms=device_monotonic_ms,
                        server_received_at_ms=received_at_ms,
                        max_server_drift_ms=self.image_max_server_drift_ms,
                    ),
                    source="server_audio_aligned_image_anchor",
                )
        else:
            del captured_at_ms  # Legacy device wall time is diagnostic only.
            fallback_anchor = ServerClockAnchor(
                server_anchor_ms=received_at_ms,
                device_monotonic_anchor_ms=None,
                timezone_name=BEIJING_TIMEZONE,
            )
            capture_time = fallback_anchor.map(
                device_monotonic_ms=device_monotonic_ms,
                server_received_at_ms=received_at_ms,
            )
        evidence = await asyncio.to_thread(
            self.store.write_image,
            self.user_id,
            stream_id,
            index,
            capture_time.captured_at_ms,
            suffix,
            body,
            device_monotonic_ms=capture_time.device_monotonic_ms,
            server_received_at_ms=capture_time.server_received_at_ms,
            server_anchor_ms=capture_time.server_anchor_ms,
            device_monotonic_anchor_ms=capture_time.device_monotonic_anchor_ms,
            timezone_name=capture_time.timezone_name,
            capture_time_source=capture_time.source,
            device_id=device_id,
            boot_id=boot_id,
            media_stream_id=media_stream_id,
            captured_at_device_ms=captured_at_device_ms,
            clock_synced=clock_synced,
            duration_ms=duration_ms,
            clock_anomaly=clock_anomaly,
            clock_deviation_ms=clock_deviation_ms,
        )
        if window and window.device_id == device_id:
            sequence_key = (media_stream_id or stream_id, index)
            existing = window.image_sequence_evidence.get(sequence_key)
            if existing is not None:
                if existing.sha256 != evidence.sha256:
                    raise ValueError(
                        f"image sequence conflict at index {index}: different content"
                    )
                return existing
            window.image_sequence_evidence[sequence_key] = evidence
            if evidence.captured_at_ms < window.current_window_started_at_ms:
                window.cross_window_images.append(evidence)
            else:
                window.images.append(evidence)
            window.image_width = width or window.image_width
            window.image_height = height or window.image_height
        elif boot_id:
            key = (device_id, f"{device_id}-{boot_id}")
            pending = self._unassigned_images.setdefault(key, [])
            if not any(item.evidence_id == evidence.evidence_id for item in pending):
                pending.append(evidence)
        return evidence

    @staticmethod
    def _refresh_audio_gaps(window: CaptureWindow) -> None:
        if not window.pending_audio_chunks:
            window.audio_gaps = []
            return
        maximum = max(window.pending_audio_chunks)
        missing = [
            index
            for index in range(window.expected_index, maximum)
            if index not in window.pending_audio_chunks
        ]
        ranges: list[dict[str, int]] = []
        for index in missing:
            if ranges and ranges[-1]["to_index"] + 1 == index:
                ranges[-1]["to_index"] = index
            else:
                ranges.append({"from_index": index, "to_index": index})
        window.audio_gaps = ranges

    def image_job_context(self, *, device_id: str, stream_id: str) -> dict[str, str]:
        window = self._windows_by_stream.get(stream_id)
        if window is None or window.device_id != device_id:
            return {"window_id": stream_id, "boot_session_key": stream_id}
        return {
            "window_id": window.session_id,
            "boot_session_key": window.boot_session_key,
        }

    def _require_window(self, device_id: str, stream_id: str) -> CaptureWindow:
        window = self._windows_by_device.get(device_id)
        if not window or window.stream_id != stream_id:
            raise ValueError(f"capture stream is not active: {stream_id}")
        return window

    def _window_reached_max_duration(
        self,
        window: CaptureWindow,
        captured_at_ms: int,
    ) -> bool:
        if self.max_window_ms <= 0 or not window.audio_chunks:
            return False
        first_captured_at_ms = min(item.captured_at_ms for item in window.audio_chunks)
        bytes_per_sample = 2 * max(1, window.format.channels)
        audio_bytes = sum(item.path.stat().st_size for item in window.audio_chunks)
        duration_ms = (
            audio_bytes * 1000 // (window.format.sample_rate * bytes_per_sample)
        )
        return (
            captured_at_ms - first_captured_at_ms >= self.max_window_ms
            or duration_ms >= self.max_window_ms
        )

    async def _close_window(
        self,
        window: CaptureWindow,
        *,
        reason: str,
        freeze_before_grace: bool = False,
    ) -> dict:
        if not freeze_before_grace and self.image_late_grace_ms > 0:
            await asyncio.sleep(self.image_late_grace_ms / 1000)
        session_id = window.session_id
        audio_chunks = sorted(
            window.audio_chunks,
            key=lambda item: item.sequence if item.sequence is not None else -1,
        )
        window_ended_at_ms = max(
            item.captured_at_ms + max(0, item.duration_ms)
            for item in audio_chunks
        )
        # A defensive clamp for streams that were already active when an ESP
        # counter reset occurred. Contracts must never contain a negative
        # technical window.
        window_started_at_ms = min(window.current_window_started_at_ms, window_ended_at_ms)
        audio_gaps = list(window.audio_gaps)
        speech_activity = list(window.speech_activity)
        speech_active_at_start = window.speech_active_at_window_start
        speech_active_at_end = window.detector.active
        cross_window_images = list(window.cross_window_images)

        # Freeze and advance before any grace period or downstream model call.
        # This lets an HTTP uploader keep accepting the next five-second WAV
        # while the previous 30-second window is interpreted asynchronously.
        window.audio_chunks.clear()
        window.audio_gaps.clear()
        window.speech_activity.clear()
        window.cross_window_images.clear()
        window.current_window_started_at_ms = window_ended_at_ms + 1
        window.speech_active_at_window_start = speech_active_at_end
        window.window_index += 1
        if freeze_before_grace and self.image_late_grace_ms > 0:
            await asyncio.sleep(self.image_late_grace_ms / 1000)
        late_cross_window_images = [
            item
            for item in window.cross_window_images
            if window_started_at_ms <= item.captured_at_ms <= window_ended_at_ms
        ]
        images = [
            item
            for item in window.images
            if window_started_at_ms <= item.captured_at_ms <= window_ended_at_ms
        ] + late_cross_window_images
        images.sort(
            key=lambda item: (
                item.captured_at_ms,
                item.sequence if item.sequence is not None else -1,
            )
        )
        window.images = [item for item in window.images if item not in images]
        window.cross_window_images = [
            item for item in window.cross_window_images if item not in late_cross_window_images
        ]
        clock = {
            "time_basis": "server_anchor_monotonic",
            "timezone_name": window.clock_anchor.timezone_name,
            "server_anchor_ms": window.clock_anchor.server_anchor_ms,
            "device_monotonic_anchor_ms": window.clock_anchor.device_monotonic_anchor_ms,
        }
        window_metadata = build_technical_window_contract(
            window_id=session_id,
            boot_session_key=window.boot_session_key,
            start_ms=window_started_at_ms,
            end_ms=window_ended_at_ms,
            audio_chunks=audio_chunks,
            images=images,
            cross_window_images=cross_window_images,
            sample_rate=window.format.sample_rate,
            image_width=window.image_width,
            image_height=window.image_height,
            audio_gaps=audio_gaps,
            speech_activity=speech_activity,
            speech_active_at_start=speech_active_at_start,
            speech_active_at_end=speech_active_at_end,
            close_reason=reason,
            clock=clock,
        )
        try:
            result = await self.bridge.close_window(
                session_id=session_id,
                user_id=self.user_id,
                sender_name=self.sender_name,
                audio_chunks=audio_chunks,
                images=images,
                sample_rate=window.format.sample_rate,
                image_width=window.image_width,
                image_height=window.image_height,
                window_metadata=window_metadata,
            )
        except Exception as exc:
            return {
                "type": "capture.window.failed",
                "stream_id": window.stream_id,
                "session_id": session_id,
                "reason": reason,
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "technical_window": window_metadata,
            }
        if result.get("status") == "pending":
            return {
                "type": "capture.window.pending",
                "stream_id": window.stream_id,
                "session_id": session_id,
                "reason": reason,
                "everos": result["everos"],
                "media_uris": result["media_uris"],
                "manifest": result["manifest"],
                "technical_window": window_metadata,
            }
        return {
            "type": "capture.window.closed",
            "stream_id": window.stream_id,
            "session_id": session_id,
            "reason": reason,
            "everos": result["everos"],
            "media_uris": result["media_uris"],
            "manifest": result["manifest"],
            "technical_window": window_metadata,
        }
