"""Realtime event aggregation, lifecycle, evidence, and persistence."""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from buildguard.realtime.clip_writer import ClipWriter
from buildguard.realtime.frame_buffer import FrameBuffer
from buildguard.realtime.schemas import (
    CameraStatus,
    EventCandidate,
    EventState,
    RealtimeRiskEvent,
)
from buildguard.schemas.common import Severity
from buildguard.storage.database import Database
from buildguard.storage.models import CameraStatusModel, RealtimeEventModel
from buildguard.utils.time import utc_now

LOGGER = logging.getLogger(__name__)


class RealtimeStore(ABC):
    @abstractmethod
    def save_camera_status(self, status: CameraStatus) -> None:
        """Create or update one camera status."""

    @abstractmethod
    def list_camera_statuses(self) -> list[CameraStatus]:
        """Return the latest persisted status for every camera."""

    @abstractmethod
    def save_event(self, event: RealtimeRiskEvent) -> None:
        """Create or replace one realtime event."""

    @abstractmethod
    def list_events(self) -> list[RealtimeRiskEvent]:
        """Return persisted realtime events."""


class InMemoryRealtimeStore(RealtimeStore):
    def __init__(self) -> None:
        self.statuses: dict[str, CameraStatus] = {}
        self.events: dict[str, RealtimeRiskEvent] = {}
        self._lock = threading.RLock()

    def save_camera_status(self, status: CameraStatus) -> None:
        with self._lock:
            self.statuses[status.camera_id] = status.model_copy(deep=True)

    def list_camera_statuses(self) -> list[CameraStatus]:
        with self._lock:
            return [self.statuses[key].model_copy(deep=True) for key in sorted(self.statuses)]

    def save_event(self, event: RealtimeRiskEvent) -> None:
        with self._lock:
            self.events[event.id] = event.model_copy(deep=True)

    def list_events(self) -> list[RealtimeRiskEvent]:
        with self._lock:
            return [
                event.model_copy(deep=True)
                for event in sorted(
                    self.events.values(),
                    key=lambda item: (item.started_at, item.id),
                    reverse=True,
                )
            ]


class DatabaseRealtimeStore(RealtimeStore):
    """SQLAlchemy-backed camera status and realtime event store."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_camera_status(self, status: CameraStatus) -> None:
        payload = status.model_dump(mode="json")
        with self.database.session() as session:
            entity = session.scalar(
                select(CameraStatusModel).where(CameraStatusModel.camera_id == status.camera_id)
            )
            if entity is None:
                session.add(
                    CameraStatusModel(
                        camera_id=status.camera_id,
                        source_type=status.source_type,
                        state=status.state.value,
                        status_json=payload,
                    )
                )
            else:
                entity.source_type = status.source_type
                entity.state = status.state.value
                entity.status_json = payload

    def list_camera_statuses(self) -> list[CameraStatus]:
        with self.database.session() as session:
            entities = session.scalars(
                select(CameraStatusModel).order_by(CameraStatusModel.camera_id)
            ).all()
            return [CameraStatus.model_validate(entity.status_json) for entity in entities]

    def save_event(self, event: RealtimeRiskEvent) -> None:
        payload = event.model_dump(mode="json")
        with self.database.session() as session:
            entity = session.get(RealtimeEventModel, event.id)
            if entity is None:
                session.add(
                    RealtimeEventModel(
                        id=event.id,
                        camera_id=event.camera_id,
                        event_type=event.event_type,
                        track_id=event.track_id,
                        status=event.status.value,
                        severity=event.severity.value,
                        started_at=event.started_at,
                        last_seen_at=event.last_seen_at,
                        event_json=payload,
                    )
                )
            else:
                entity.camera_id = event.camera_id
                entity.event_type = event.event_type
                entity.track_id = event.track_id
                entity.status = event.status.value
                entity.severity = event.severity.value
                entity.started_at = event.started_at
                entity.last_seen_at = event.last_seen_at
                entity.event_json = payload

    def list_events(self) -> list[RealtimeRiskEvent]:
        with self.database.session() as session:
            entities = session.scalars(
                select(RealtimeEventModel).order_by(RealtimeEventModel.started_at.desc())
            ).all()
            return [RealtimeRiskEvent.model_validate(entity.event_json) for entity in entities]


class EventEngine:
    def __init__(
        self,
        *,
        store: RealtimeStore,
        writer: ClipWriter,
        severity_by_type: Mapping[str, str],
        cooldown_seconds: float,
        resolve_seconds: float,
        region_iou_threshold: float,
        before_seconds: float,
        after_seconds: float,
        save_clips: bool,
    ) -> None:
        if cooldown_seconds < 0 or resolve_seconds <= 0:
            raise ValueError("Event time limits are invalid")
        if not 0 < region_iou_threshold <= 1:
            raise ValueError("Event region IoU threshold must be within (0, 1]")
        self.store = store
        self.writer = writer
        self.severity_by_type = dict(severity_by_type)
        self.cooldown_seconds = cooldown_seconds
        self.resolve_seconds = resolve_seconds
        self.region_iou_threshold = region_iou_threshold
        self.before_seconds = before_seconds
        self.after_seconds = after_seconds
        self.save_clips = save_clips
        self.events: dict[str, RealtimeRiskEvent] = {
            event.id: event for event in store.list_events()
        }
        self.buffers: dict[str, FrameBuffer] = {}
        self._lock = threading.RLock()

    def register_buffer(self, camera_id: str, buffer: FrameBuffer) -> None:
        self.buffers[camera_id] = buffer

    @staticmethod
    def _history(candidate: EventCandidate) -> dict[str, object]:
        return {
            "captured_at": candidate.frame.captured_at.isoformat(),
            "sequence": candidate.frame.sequence,
            "source_time_seconds": candidate.frame.source_time_seconds,
            "frame_sha256": hashlib.sha256(candidate.frame.image.tobytes()).hexdigest(),
            "confidence": candidate.confidence,
            "calibration_decision": candidate.calibration_decision,
            "track_id": candidate.track_id,
            "bbox": candidate.bbox.model_dump(mode="json"),
            "detections": [item.model_dump(mode="json") for item in candidate.detections],
        }

    @staticmethod
    def _file_sha256(path: Path | None) -> str | None:
        if path is None or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _persist(self, event: RealtimeRiskEvent) -> None:
        try:
            self.store.save_event(event)
        except Exception as exc:
            LOGGER.error("Realtime event persistence failed: %s", exc)

    def _write_frame(
        self,
        event: RealtimeRiskEvent,
        kind: str,
        candidate: EventCandidate,
    ) -> Path | None:
        try:
            return self.writer.write_frame(event.id, kind, candidate.frame)
        except Exception as exc:
            LOGGER.warning("Event evidence frame write failed: %s", exc)
            return None

    def _matches(
        self,
        event: RealtimeRiskEvent,
        candidate: EventCandidate,
    ) -> bool:
        if event.status in {EventState.RESOLVED, EventState.DISMISSED}:
            return False
        if event.camera_id != candidate.camera_id or event.event_type != candidate.event_type:
            return False
        gap = (candidate.frame.captured_at - event.last_seen_at).total_seconds()
        if gap < 0 or gap >= self.cooldown_seconds:
            return False
        same_track = (
            event.track_id is not None
            and candidate.track_id is not None
            and event.track_id == candidate.track_id
        )
        same_region = event.region.iou(candidate.bbox) >= self.region_iou_threshold
        return same_track or same_region

    def process(self, candidate: EventCandidate) -> RealtimeRiskEvent:
        with self._lock:
            matching = next(
                (event for event in self.events.values() if self._matches(event, candidate)),
                None,
            )
            if matching is None:
                severity = Severity(self.severity_by_type.get(candidate.event_type, "normal"))
                event = RealtimeRiskEvent(
                    camera_id=candidate.camera_id,
                    event_type=candidate.event_type,
                    track_id=candidate.track_id,
                    status=(EventState.ACTIVE if candidate.confirmed else EventState.PENDING),
                    severity=severity,
                    started_at=candidate.frame.captured_at,
                    last_seen_at=candidate.frame.captured_at,
                    max_confidence=candidate.confidence,
                    region=candidate.bbox,
                    detection_history=[self._history(candidate)],
                )
                start_path = self._write_frame(event, "start", candidate)
                max_path = self._write_frame(event, "maximum", candidate)
                metadata: dict[str, object] = {
                    "calibration_decision": candidate.calibration_decision,
                    "evidence_sha256": {
                        "start": self._file_sha256(start_path),
                        "maximum": self._file_sha256(max_path),
                    },
                }
                buffer = self.buffers.get(candidate.camera_id)
                if self.save_clips and candidate.confirmed and buffer is not None:
                    pre_roll = buffer.between(
                        candidate.frame.captured_at
                        - timedelta(seconds=self.before_seconds),
                        candidate.frame.captured_at,
                    )
                    try:
                        pre_roll_path = self.writer.write_clip(
                            f"{event.id}-pre",
                            pre_roll,
                        )
                        metadata["pre_roll_clip_path"] = pre_roll_path
                        metadata["pre_roll_sha256"] = self._file_sha256(
                            pre_roll_path
                        )
                    except Exception as exc:
                        metadata["evidence_incomplete"] = True
                        LOGGER.warning("Event pre-roll clip write failed: %s", exc)
                event = event.model_copy(
                    update={
                        "start_frame_path": start_path,
                        "max_confidence_frame_path": max_path,
                        "metadata": metadata,
                    }
                )
                self.events[event.id] = event
                self._persist(event)
                return event.model_copy(deep=True)
            updates: dict[str, object] = {
                "last_seen_at": candidate.frame.captured_at,
                "track_id": matching.track_id or candidate.track_id,
                "region": candidate.bbox,
                "detection_history": [
                    *matching.detection_history,
                    self._history(candidate),
                ][-500:],
            }
            if candidate.confirmed and matching.status == EventState.PENDING:
                updates["status"] = EventState.ACTIVE
            if candidate.confidence > matching.max_confidence:
                updates["max_confidence"] = candidate.confidence
                updates["max_confidence_frame_path"] = self._write_frame(
                    matching, "maximum", candidate
                )
                maximum_path = updates["max_confidence_frame_path"]
                metadata = dict(matching.metadata)
                raw_evidence_hashes = metadata.get("evidence_sha256", {})
                evidence_hashes = (
                    dict(raw_evidence_hashes)
                    if isinstance(raw_evidence_hashes, dict)
                    else {}
                )
                evidence_hashes["maximum"] = self._file_sha256(
                    maximum_path if isinstance(maximum_path, Path) else None
                )
                metadata["evidence_sha256"] = evidence_hashes
                updates["metadata"] = metadata
            updated = matching.model_copy(update=updates)
            self.events[updated.id] = updated
            self._persist(updated)
            return updated.model_copy(deep=True)

    def _finish(
        self,
        event: RealtimeRiskEvent,
        status: EventState,
        ended_at: datetime,
    ) -> RealtimeRiskEvent:
        effective_end = max(ended_at, event.last_seen_at)
        updates: dict[str, object] = {
            "status": status,
            "ended_at": effective_end,
        }
        buffer = self.buffers.get(event.camera_id)
        latest = buffer.latest() if buffer is not None else None
        if latest is not None:
            candidate = EventCandidate(
                camera_id=event.camera_id,
                event_type=event.event_type,
                track_id=event.track_id,
                bbox=event.region,
                confidence=event.max_confidence,
                confirmed=True,
                frame=latest,
            )
            updates["end_frame_path"] = self._write_frame(event, "end", candidate)
        if self.save_clips and buffer is not None:
            frames = buffer.between(
                event.started_at - timedelta(seconds=self.before_seconds),
                effective_end + timedelta(seconds=self.after_seconds),
            )
            try:
                updates["clip_path"] = self.writer.write_clip(event.id, frames)
            except Exception as exc:
                LOGGER.warning("Event clip write failed: %s", exc)
        metadata = dict(event.metadata)
        evidence_hashes = dict(metadata.get("evidence_sha256", {}))
        end_path = updates.get("end_frame_path")
        clip_path = updates.get("clip_path")
        evidence_hashes["end"] = self._file_sha256(
            end_path if isinstance(end_path, Path) else None
        )
        evidence_hashes["clip"] = self._file_sha256(
            clip_path if isinstance(clip_path, Path) else None
        )
        metadata["evidence_sha256"] = evidence_hashes
        if self.save_clips and clip_path is None:
            metadata["evidence_incomplete"] = True
        updates["metadata"] = metadata
        updated = event.model_copy(update=updates)
        self.events[updated.id] = updated
        self._persist(updated)
        return updated.model_copy(deep=True)

    def resolve_stale(self, now: datetime | None = None) -> list[RealtimeRiskEvent]:
        current = now or utc_now()
        with self._lock:
            stale = [
                event
                for event in self.events.values()
                if event.status
                in {
                    EventState.PENDING,
                    EventState.ACTIVE,
                    EventState.ACKNOWLEDGED,
                }
                and (current - event.last_seen_at).total_seconds() >= self.resolve_seconds
            ]
            return [self._finish(event, EventState.RESOLVED, current) for event in stale]

    def resolve_camera(
        self,
        camera_id: str,
        now: datetime | None = None,
    ) -> list[RealtimeRiskEvent]:
        current = now or utc_now()
        with self._lock:
            active = [
                event
                for event in self.events.values()
                if event.camera_id == camera_id
                and event.status
                in {
                    EventState.PENDING,
                    EventState.ACTIVE,
                    EventState.ACKNOWLEDGED,
                }
            ]
            return [self._finish(event, EventState.RESOLVED, current) for event in active]

    def acknowledge(self, event_id: str) -> RealtimeRiskEvent:
        with self._lock:
            event = self.events.get(event_id)
            if event is None:
                raise KeyError(f"Realtime event not found: {event_id}")
            if event.status == EventState.ACKNOWLEDGED:
                return event.model_copy(deep=True)
            if event.status not in {EventState.PENDING, EventState.ACTIVE}:
                raise ValueError(f"Event cannot be acknowledged from {event.status}")
            updated = event.model_copy(update={"status": EventState.ACKNOWLEDGED})
            self.events[event_id] = updated
            self._persist(updated)
            return updated.model_copy(deep=True)

    def close(
        self,
        event_id: str,
        *,
        dismissed: bool = False,
        now: datetime | None = None,
    ) -> RealtimeRiskEvent:
        with self._lock:
            event = self.events.get(event_id)
            if event is None:
                raise KeyError(f"Realtime event not found: {event_id}")
            if event.status in {EventState.RESOLVED, EventState.DISMISSED}:
                return event.model_copy(deep=True)
            return self._finish(
                event,
                EventState.DISMISSED if dismissed else EventState.RESOLVED,
                now or utc_now(),
            )

    def query(
        self,
        *,
        camera_id: str | None = None,
        statuses: list[EventState] | None = None,
        limit: int = 20,
    ) -> list[RealtimeRiskEvent]:
        if not 1 <= limit <= 500:
            raise ValueError("Event query limit must be within 1..500")
        allowed = set(statuses or [])
        with self._lock:
            results = [
                event
                for event in self.events.values()
                if (camera_id is None or event.camera_id == camera_id)
                and (not allowed or event.status in allowed)
            ]
            results.sort(
                key=lambda event: (event.last_seen_at, event.id),
                reverse=True,
            )
            return [event.model_copy(deep=True) for event in results[:limit]]
