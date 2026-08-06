"""Bounded reader/inference/event workers and realtime tool registration."""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from buildguard.config import CameraConfig, CameraPolicyConfig, RealtimeConfig, Settings
from buildguard.exceptions import ConfigurationError
from buildguard.realtime.calibration import ConformalEventCalibrator
from buildguard.realtime.clip_writer import ClipWriter
from buildguard.realtime.event_engine import (
    DatabaseRealtimeStore,
    EventEngine,
    RealtimeStore,
)
from buildguard.realtime.file_source import LocalVideoSource
from buildguard.realtime.frame_buffer import BoundedFrameQueue, FrameBuffer
from buildguard.realtime.ppe_events import PPEEventDetector
from buildguard.realtime.reconnect import ExponentialReconnect
from buildguard.realtime.rtsp_source import RtspVideoSource
from buildguard.realtime.sampler import AdaptiveMotionSampler
from buildguard.realtime.schemas import (
    CameraActionInput,
    CameraActionOutput,
    CameraState,
    CameraStatus,
    EventActionInput,
    EventActionOutput,
    EventCandidate,
    EventState,
    FramePriority,
    ListCameraStatusInput,
    ListCameraStatusOutput,
    QueryRecentEventsInput,
    QueryRecentEventsOutput,
    RealtimeRiskEvent,
    SamplingMode,
    VideoFrame,
)
from buildguard.realtime.source import VideoSource
from buildguard.realtime.stream_clock import StreamClock
from buildguard.realtime.temporal_confirmation import MOfNConfirmation
from buildguard.realtime.tracker import (
    ByteTrackTracker,
    ObservationCentricByteTrackTracker,
    SimpleIoUTracker,
    Tracker,
)
from buildguard.realtime.usb_source import UsbCameraSource
from buildguard.schemas.vision import Detection
from buildguard.security.path_guard import PathGuard
from buildguard.storage.database import Database
from buildguard.tools.base import ToolDefinition
from buildguard.tools.registry import ToolRegistry
from buildguard.vision.fusion import fuse_detections
from buildguard.vision.preprocessing import DecodedImage
from buildguard.vision.registry import VisionModelRegistry
from buildguard.vision.service import VisionInspectionService

LOGGER = logging.getLogger(__name__)
InferenceFunction = Callable[[VideoFrame], list[Detection]]
SourceFactory = Callable[[CameraConfig], VideoSource]
PerformanceSink = Callable[[str, float, dict[str, object]], None]
EventSink = Callable[[RealtimeRiskEvent], bool | None]


@dataclass
class _CameraRuntime:
    source: VideoSource
    buffer: FrameBuffer
    sampler: AdaptiveMotionSampler
    tracker: Tracker
    confirmation: MOfNConfirmation
    ppe_events: PPEEventDetector
    inference_queue: BoundedFrameQueue
    event_queue: queue.Queue[EventCandidate]
    stop_event: threading.Event
    threads: list[threading.Thread]
    confirmation_started: dict[tuple[str, str], datetime]
    reported_confirmations: set[tuple[str, str]]
    sampled_timestamps: deque[float]
    clock: StreamClock


class CameraManager:
    """Keep each camera failure contained to its own bounded worker set."""

    def __init__(
        self,
        config: RealtimeConfig,
        *,
        store: RealtimeStore,
        event_engine: EventEngine,
        inference: InferenceFunction,
        source_factory: SourceFactory,
        performance_sink: PerformanceSink | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.event_engine = event_engine
        self.inference = inference
        self.source_factory = source_factory
        self.performance_sink = performance_sink
        self.event_sink = event_sink
        try:
            self.calibrator = ConformalEventCalibrator.from_path(
                config.optimization.calibration_path,
                required=config.optimization.calibration_required,
            )
        except Exception:
            if config.optimization.calibration_required:
                raise
            LOGGER.exception(
                "Realtime calibration unavailable; temporal recall fallback remains active"
            )
            self.calibrator = ConformalEventCalibrator()
        self._dispatched_event_ids: set[str] = set()
        self.camera_configs: dict[str, CameraConfig] = {}
        self.sources: dict[str, VideoSource] = {}
        self.runtimes: dict[str, _CameraRuntime] = {}
        self._lock = threading.RLock()
        for camera in config.cameras:
            self.register(camera)

    def register(
        self,
        camera: CameraConfig,
        policy: CameraPolicyConfig | None = None,
    ) -> CameraStatus:
        with self._lock:
            if camera.camera_id in self.camera_configs:
                raise ValueError(f"Camera is already registered: {camera.camera_id}")
            source = self.source_factory(camera)
            self.camera_configs[camera.camera_id] = camera
            self.sources[camera.camera_id] = source
            if policy is not None:
                self.config.camera_policies[camera.camera_id] = policy
            status = source.status()
            self.store.save_camera_status(status)
            return status

    def unregister(self, camera_id: str) -> CameraStatus:
        """Remove a stopped camera while preserving its persisted event history."""
        with self._lock:
            if camera_id not in self.camera_configs:
                raise KeyError(f"Unknown camera: {camera_id}")
            status = self.sources[camera_id].status()
            runtime = self.runtimes.get(camera_id)
            if runtime is not None and any(thread.is_alive() for thread in runtime.threads):
                raise RuntimeError("Stop camera monitoring before removing the camera")
            self.sources[camera_id].close()
            self.runtimes.pop(camera_id, None)
            self.sources.pop(camera_id, None)
            self.camera_configs.pop(camera_id, None)
            self.config.camera_policies.pop(camera_id, None)
            return status

    def update_policy(
        self,
        camera_id: str,
        policy: CameraPolicyConfig,
    ) -> CameraPolicyConfig:
        with self._lock:
            if camera_id not in self.camera_configs:
                raise KeyError(f"Unknown camera: {camera_id}")
            self.config.camera_policies[camera_id] = policy
            runtime = self.runtimes.get(camera_id)
            if runtime is not None:
                runtime.sampler = AdaptiveMotionSampler(
                    policy,
                    self.config.optimization,
                )
            return policy.model_copy(deep=True)

    def set_event_sink(self, sink: EventSink | None) -> None:
        with self._lock:
            self.event_sink = sink

    def latest_frame(self, camera_id: str) -> VideoFrame | None:
        with self._lock:
            if camera_id not in self.camera_configs:
                raise KeyError(f"Unknown camera: {camera_id}")
            runtime = self.runtimes.get(camera_id)
            return runtime.buffer.latest() if runtime is not None else None

    def _policy(self, camera_id: str) -> CameraPolicyConfig:
        return self.config.camera_policies.get(
            camera_id,
            CameraPolicyConfig(
                static_fps=self.config.static_fps,
                low_motion_fps=self.config.low_motion_fps,
                active_fps=self.config.active_fps,
                suspected_fps=min(10, self.config.suspected_fps),
            ),
        )

    def _new_runtime(self, camera_id: str) -> _CameraRuntime:
        source = self.sources[camera_id]
        buffer = FrameBuffer(
            self.config.buffer_seconds,
            self.config.buffer_max_frames,
            self.config.buffer_memory_mb,
        )
        self.event_engine.register_buffer(camera_id, buffer)
        tracker: Tracker
        tracker_algorithm: str = self.config.tracker_algorithm
        if (
            tracker_algorithm == "bytetrack"
            and self.config.optimization.enabled
            and self.config.optimization.observation_centric_tracking
        ):
            tracker = ObservationCentricByteTrackTracker(
                iou_threshold=self.config.tracker_iou_threshold,
                high_confidence=self.config.tracker_high_confidence,
                low_confidence=self.config.tracker_low_confidence,
                max_age=self.config.tracker_max_age,
                minimum_hits=self.config.tracker_min_hits,
                direction_cost_weight=(
                    self.config.optimization.direction_cost_weight
                ),
            )
            tracker_algorithm = "oc_bytetrack"
        elif tracker_algorithm == "bytetrack":
            tracker = ByteTrackTracker(
                iou_threshold=self.config.tracker_iou_threshold,
                high_confidence=self.config.tracker_high_confidence,
                low_confidence=self.config.tracker_low_confidence,
                max_age=self.config.tracker_max_age,
                minimum_hits=self.config.tracker_min_hits,
            )
        else:
            tracker = SimpleIoUTracker(
                iou_threshold=self.config.tracker_iou_threshold,
                max_age=self.config.tracker_max_age,
                minimum_hits=self.config.tracker_min_hits,
            )
        return _CameraRuntime(
            source=source,
            buffer=buffer,
            sampler=AdaptiveMotionSampler(
                self._policy(camera_id),
                self.config.optimization,
            ),
            tracker=tracker,
            confirmation=MOfNConfirmation(
                self.config.temporal_rules,
                time_evidence_enabled=(
                    self.config.optimization.enabled
                    and self.config.optimization.time_evidence_enabled
                ),
                evidence_window_seconds=(
                    self.config.optimization.evidence_window_seconds
                ),
                evidence_half_life_seconds=(
                    self.config.optimization.evidence_half_life_seconds
                ),
                evidence_min_positive_seconds=(
                    self.config.optimization.evidence_min_positive_seconds
                ),
                evidence_confirm_threshold=(
                    self.config.optimization.evidence_confirm_threshold
                ),
            ),
            ppe_events=PPEEventDetector(
                self.config.ppe,
                tracker_iou_threshold=self.config.tracker_iou_threshold,
                tracker_min_hits=self.config.tracker_min_hits,
                tracker_algorithm=tracker_algorithm,
                optimization=self.config.optimization,
            ),
            inference_queue=BoundedFrameQueue(self.config.inference_queue_size),
            event_queue=queue.Queue(maxsize=self.config.event_queue_size),
            stop_event=threading.Event(),
            threads=[],
            confirmation_started={},
            reported_confirmations=set(),
            sampled_timestamps=deque(),
            clock=StreamClock(
                pace=(
                    self.config.optimization.enabled
                    and self.config.optimization.pace_local_video
                    and source.status().source_type == "local"
                ),
                playback_speed=self.config.optimization.local_playback_speed,
            ),
        )

    @staticmethod
    def _frame_timestamp(runtime: _CameraRuntime, frame: VideoFrame) -> float:
        return (
            frame.source_time_seconds
            if runtime.source.status().source_type == "local"
            else frame.captured_at.timestamp()
        )

    def _queue_policy(
        self,
        runtime: _CameraRuntime,
    ) -> tuple[FramePriority, float]:
        mode = runtime.sampler.mode
        optimization = self.config.optimization
        if mode == SamplingMode.SUSPECTED:
            return FramePriority.SUSPECTED, optimization.risk_frame_deadline_seconds
        if mode in {SamplingMode.ACTIVE, SamplingMode.RECOVERY}:
            return FramePriority.RECOVERY, optimization.normal_frame_deadline_seconds
        if mode == SamplingMode.STATIC:
            return FramePriority.HEARTBEAT, optimization.normal_frame_deadline_seconds
        return FramePriority.NORMAL, optimization.normal_frame_deadline_seconds

    def _calibrated_candidate(self, candidate: EventCandidate) -> EventCandidate | None:
        decision = self.calibrator.decide(
            candidate.event_type,
            candidate.confidence,
        )
        if decision == "no_event":
            return None
        return candidate.model_copy(
            update={
                "confirmed": (
                    candidate.confirmed
                    if decision in {"event", "uncalibrated"}
                    else False
                ),
                "calibration_decision": decision,
            }
        )

    @staticmethod
    def _sampled_fps(runtime: _CameraRuntime, timestamp: float) -> float:
        samples = runtime.sampled_timestamps
        if samples and timestamp < samples[-1]:
            samples.clear()
        samples.append(timestamp)
        cutoff = timestamp - 5
        while samples and samples[0] < cutoff:
            samples.popleft()
        if len(samples) < 2:
            return 0.0
        duration = samples[-1] - samples[0]
        return (len(samples) - 1) / duration if duration > 0 else 0.0

    def _reader_loop(self, camera_id: str, runtime: _CameraRuntime) -> None:
        source = runtime.source
        while not runtime.stop_event.is_set():
            try:
                frame = source.read()
                if frame is None:
                    status = source.status()
                    if status.source_type == "local":
                        runtime.stop_event.set()
                        break
                    if not source.reconnect():
                        runtime.stop_event.wait(self.config.reconnect_initial_seconds)
                    continue
                if runtime.source.status().source_type == "local":
                    delay = runtime.clock.delay_seconds(frame.source_time_seconds)
                    if delay > 0 and runtime.stop_event.wait(delay):
                        break
                runtime.buffer.append(frame)
                runtime.sampler.observe(frame.image)
                timestamp = self._frame_timestamp(runtime, frame)
                current_fps = source.status().current_fps
                if runtime.sampler.should_sample(timestamp):
                    priority, max_age = self._queue_policy(runtime)
                    try:
                        accepted = runtime.inference_queue.put(
                            frame,
                            timeout=0.25,
                            priority=priority,
                            max_age_seconds=(
                                max_age if self.config.optimization.enabled else None
                            ),
                        )
                    except TimeoutError:
                        accepted = False
                        LOGGER.error(
                            "Camera %s risk frame missed its bounded queue wait",
                            camera_id,
                        )
                    if accepted:
                        source.mark_sampled()
                        current_fps = self._sampled_fps(runtime, timestamp)
                source.update_runtime_metrics(
                    sampling_mode=runtime.sampler.mode,
                    target_fps=runtime.sampler.fps,
                    current_fps=current_fps,
                    motion_score=runtime.sampler.motion_score,
                    inference_queue_length=len(runtime.inference_queue),
                    event_queue_length=runtime.event_queue.qsize(),
                    dropped_normal_frames=(runtime.inference_queue.dropped_normal_frames),
                )
                self.store.save_camera_status(source.status())
            except Exception as exc:
                LOGGER.warning("Camera %s reader failure contained: %s", camera_id, exc)
                runtime.stop_event.wait(self.config.reconnect_initial_seconds)

    def _record_performance(
        self,
        operation: str,
        duration_ms: float,
        metrics: dict[str, object],
    ) -> None:
        if self.performance_sink is None:
            return
        try:
            self.performance_sink(operation, duration_ms, metrics)
        except Exception as exc:
            LOGGER.warning(
                "Performance sink failed without stopping camera processing: %s",
                exc,
            )

    def _enqueue_event(
        self,
        runtime: _CameraRuntime,
        candidate: EventCandidate,
    ) -> None:
        normalized_type = self.config.event_class_map.get(
            candidate.event_type,
            candidate.event_type,
        )
        if normalized_type != candidate.event_type:
            candidate = candidate.model_copy(update={"event_type": normalized_type})
        try:
            runtime.event_queue.put(candidate, timeout=0.25)
        except queue.Full:
            LOGGER.warning(
                "Event queue full; processing key candidate synchronously for %s",
                candidate.camera_id,
            )
            self.event_engine.process(candidate)

    def _inference_loop(self, camera_id: str, runtime: _CameraRuntime) -> None:
        while not runtime.stop_event.is_set() or len(runtime.inference_queue):
            try:
                frame = runtime.inference_queue.get(timeout=0.1)
            except TimeoutError:
                continue
            try:
                inference_started = time.perf_counter()
                detections = self.inference(frame)
                if self.performance_sink is not None:
                    duration_ms = (time.perf_counter() - inference_started) * 1000
                    self._record_performance(
                        "realtime_vision_inference",
                        duration_ms,
                        {
                            "camera_id": camera_id,
                            "frame_sequence": frame.sequence,
                            "frame_queue_age_ms": round(
                                runtime.inference_queue.last_dequeue_age_ms,
                                3,
                            ),
                        },
                    )
                tracked = runtime.tracker.update(detections, frame.sequence)
                timestamp = self._frame_timestamp(runtime, frame)
                tracked_people = [
                    item for item in tracked if item.detection.label == "person"
                ]
                frame_candidates: list[EventCandidate] = []
                ppe_candidates = runtime.ppe_events.process(
                    frame,
                    detections,
                    tracked_persons=tracked_people,
                    timestamp_seconds=timestamp,
                )
                for raw_candidate in ppe_candidates:
                    candidate = self._calibrated_candidate(raw_candidate)
                    if candidate is None:
                        continue
                    key_frame = candidate.frame.model_copy(update={"key_frame": True})
                    runtime.buffer.append(key_frame)
                    frame_candidates.append(
                        candidate.model_copy(update={"frame": key_frame})
                    )
                observed: set[tuple[str, str]] = set()
                for observation in tracked:
                    event_type = self.config.event_class_map.get(observation.detection.label)
                    if event_type is not None:
                        observed.add((event_type, observation.track_id))
                for event_type, track_identity in runtime.confirmation.identities() - observed:
                    runtime.confirmation.update(
                        event_type,
                        track_identity,
                        detected=False,
                        confidence=0,
                        timestamp_seconds=timestamp,
                    )
                if not tracked:
                    if self.config.optimization.enabled:
                        runtime.sampler.update_feedback(
                            timestamp_seconds=timestamp,
                            active_tracks=False,
                            risk_score=max(
                                (item.confidence for item in frame_candidates),
                                default=0.0,
                            ),
                            uncertainty_score=0.0,
                        )
                    else:
                        runtime.sampler.set_suspected_risk(False)
                    for candidate in frame_candidates:
                        self._enqueue_event(runtime, candidate)
                    self.event_engine.resolve_stale(frame.captured_at)
                    continue
                for observation in tracked:
                    event_type = self.config.event_class_map.get(observation.detection.label)
                    if event_type is None or event_type not in self.config.temporal_rules:
                        continue
                    confirmation_key = (event_type, observation.track_id)
                    runtime.confirmation_started.setdefault(
                        confirmation_key,
                        frame.captured_at,
                    )
                    result = runtime.confirmation.update(
                        event_type,
                        observation.track_id,
                        detected=True,
                        confidence=observation.detection.confidence,
                        timestamp_seconds=timestamp,
                    )
                    confirmed = observation.confirmed and result.confirmed
                    if (
                        confirmed
                        and confirmation_key not in runtime.reported_confirmations
                        and self.performance_sink is not None
                    ):
                        started_at = runtime.confirmation_started[confirmation_key]
                        self._record_performance(
                            "event_confirmation",
                            max(
                                0.0,
                                (frame.captured_at - started_at).total_seconds() * 1000,
                            ),
                            {
                                "camera_id": camera_id,
                                "event_type": event_type,
                                "track_id": observation.track_id,
                            },
                        )
                        runtime.reported_confirmations.add(confirmation_key)
                    candidate_frame = frame.model_copy(update={"key_frame": confirmed})
                    if confirmed:
                        runtime.buffer.append(candidate_frame)
                    raw_candidate = EventCandidate(
                        camera_id=camera_id,
                        event_type=event_type,
                        track_id=observation.track_id,
                        bbox=observation.bbox,
                        confidence=result.smoothed_confidence,
                        confirmed=confirmed,
                        frame=candidate_frame,
                        detections=[observation],
                    )
                    candidate = self._calibrated_candidate(raw_candidate)
                    if candidate is not None:
                        frame_candidates.append(candidate)
                for candidate in frame_candidates:
                    self._enqueue_event(runtime, candidate)
                if self.config.optimization.enabled:
                    runtime.sampler.update_feedback(
                        timestamp_seconds=timestamp,
                        active_tracks=True,
                        risk_score=max(
                            (item.confidence for item in frame_candidates),
                            default=0.0,
                        ),
                        uncertainty_score=max(
                            (
                                max(
                                    1.0 - item.detection.confidence,
                                    0.0 if item.confirmed else 1.0,
                                )
                                for item in tracked
                            ),
                            default=0.0,
                        ),
                    )
                else:
                    runtime.sampler.set_suspected_risk(True)
            except Exception as exc:
                LOGGER.warning("Camera %s inference failure contained: %s", camera_id, exc)

    def _event_loop(self, camera_id: str, runtime: _CameraRuntime) -> None:
        next_recovery = 0.0
        while not runtime.stop_event.is_set() or not runtime.event_queue.empty():
            try:
                candidate = runtime.event_queue.get(timeout=0.1)
            except queue.Empty:
                self.event_engine.resolve_stale()
                now = time.monotonic()
                if now >= next_recovery:
                    self._recover_event_dispatches(camera_id)
                    next_recovery = now + 1.0
                continue
            try:
                event = self.event_engine.process(candidate)
                if (
                    candidate.confirmed
                    and event.id not in self._dispatched_event_ids
                    and self.event_sink is not None
                ):
                    try:
                        accepted = self.event_sink(event)
                        if accepted is not False:
                            self._dispatched_event_ids.add(event.id)
                    except Exception as exc:
                        LOGGER.warning(
                            "Camera %s slow-loop dispatch failed: %s",
                            camera_id,
                            exc,
                        )
            except Exception as exc:
                LOGGER.warning("Camera %s event failure contained: %s", camera_id, exc)
            finally:
                runtime.event_queue.task_done()

    def _recover_event_dispatches(self, camera_id: str) -> None:
        if self.event_sink is None:
            return
        recoverable = self.event_engine.query(
            camera_id=camera_id,
            statuses=[EventState.ACTIVE, EventState.ACKNOWLEDGED],
            limit=100,
        )
        for event in recoverable:
            if event.id in self._dispatched_event_ids:
                continue
            try:
                accepted = self.event_sink(event)
                if accepted is not False:
                    self._dispatched_event_ids.add(event.id)
            except Exception as exc:
                LOGGER.warning(
                    "Camera %s recovered slow-loop dispatch failed: %s",
                    camera_id,
                    exc,
                )

    def start(self, camera_id: str) -> CameraStatus:
        with self._lock:
            camera = self.camera_configs.get(camera_id)
            if camera is None:
                raise KeyError(f"Unknown camera: {camera_id}")
            if not camera.enabled:
                raise PermissionError(f"Camera is disabled: {camera_id}")
            existing = self.runtimes.get(camera_id)
            if existing is not None and any(thread.is_alive() for thread in existing.threads):
                return existing.source.status()
            active = sum(
                any(thread.is_alive() for thread in runtime.threads)
                for runtime in self.runtimes.values()
            )
            if active >= self.config.max_concurrent_cameras:
                raise RuntimeError(
                    f"Maximum concurrent camera limit reached: {self.config.max_concurrent_cameras}"
                )
            runtime = self._new_runtime(camera_id)
            self.runtimes[camera_id] = runtime
            opened = runtime.source.open()
            names_and_targets = [
                ("reader", self._reader_loop),
                ("inference", self._inference_loop),
                ("event", self._event_loop),
            ]
            runtime.threads = [
                threading.Thread(
                    target=target,
                    args=(camera_id, runtime),
                    name=f"buildguard-{camera_id}-{name}",
                    daemon=True,
                )
                for name, target in names_and_targets
            ]
            for thread in runtime.threads:
                thread.start()
            if not opened:
                LOGGER.warning(
                    "Camera %s started degraded; reconnect remains isolated",
                    camera_id,
                )
            return runtime.source.status()

    def stop(self, camera_id: str) -> CameraStatus:
        with self._lock:
            if camera_id not in self.sources:
                raise KeyError(f"Unknown camera: {camera_id}")
            runtime = self.runtimes.get(camera_id)
            if runtime is None:
                self.sources[camera_id].close()
                return self.sources[camera_id].status()
            runtime.stop_event.set()
            runtime.source.close()
        for thread in runtime.threads:
            thread.join(timeout=30)
        self.event_engine.resolve_camera(camera_id)
        return runtime.source.status()

    def stop_all(self) -> None:
        for camera_id in list(self.sources):
            try:
                self.stop(camera_id)
            except Exception as exc:
                LOGGER.warning("Camera %s stop failure contained: %s", camera_id, exc)

    def query_events(self, request: QueryRecentEventsInput) -> QueryRecentEventsOutput:
        return QueryRecentEventsOutput(
            events=self.event_engine.query(
                camera_id=request.camera_id,
                statuses=request.statuses,
                limit=request.limit,
            )
        )

    def acknowledge_event(self, event_id: str) -> EventActionOutput:
        return EventActionOutput(event=self.event_engine.acknowledge(event_id))

    def close_event(self, event_id: str) -> EventActionOutput:
        return EventActionOutput(event=self.event_engine.close(event_id))

    def list_status(self, include_stopped: bool = True) -> ListCameraStatusOutput:
        statuses = self.store.list_camera_statuses()
        if not include_stopped:
            statuses = [status for status in statuses if status.state != CameraState.STOPPED]
        return ListCameraStatusOutput(cameras=statuses)

    def runtime_metrics(self) -> list[dict[str, object]]:
        with self._lock:
            result: list[dict[str, object]] = []
            for camera_id in sorted(self.sources):
                runtime = self.runtimes.get(camera_id)
                status = self.sources[camera_id].status()
                result.append(
                    {
                        **status.model_dump(mode="json"),
                        "inference_queue": (
                            runtime.inference_queue.metrics()
                            if runtime is not None
                            else {
                                "length": 0,
                                "max_size": self.config.inference_queue_size,
                                "peak_size": 0,
                                "dropped_normal_frames": 0,
                                "critical_waits": 0,
                            }
                        ),
                        "freshness": (
                            runtime.inference_queue.freshness_metrics()
                            if runtime is not None
                            else {
                                "expired_normal_frames": 0,
                                "last_dequeue_age_ms": 0,
                            }
                        ),
                        "event_queue_length": (
                            runtime.event_queue.qsize() if runtime is not None else 0
                        ),
                        "worker_threads_alive": (
                            sum(thread.is_alive() for thread in runtime.threads)
                            if runtime is not None
                            else 0
                        ),
                    }
                )
            return result

    def status(self, camera_id: str) -> CameraStatus:
        with self._lock:
            source = self.sources.get(camera_id)
            if source is None:
                raise KeyError(f"Unknown camera: {camera_id}")
            return source.status()

    def is_online(self, camera_id: str) -> bool:
        return self.status(camera_id).state == CameraState.RUNNING

    def camera_policy(self, camera_id: str) -> CameraPolicyConfig:
        with self._lock:
            if camera_id not in self.camera_configs:
                raise KeyError(f"Unknown camera: {camera_id}")
            return self._policy(camera_id).model_copy(deep=True)


def _configured_source_factory(
    settings: Settings,
    store: RealtimeStore,
) -> SourceFactory:
    roots = [path.resolve() for path in settings.realtime.allowed_video_roots]
    guard = PathGuard(roots)

    def create(camera: CameraConfig) -> VideoSource:
        if camera.source_type == "local":
            if camera.file_path is None:
                raise ConfigurationError("Local camera file_path is missing")
            return LocalVideoSource(
                camera.camera_id,
                guard.resolve_read(camera.file_path),
                status_sink=store.save_camera_status,
            )
        if camera.source_type == "usb":
            if camera.usb_index is None:
                raise ConfigurationError("USB camera index is missing")
            return UsbCameraSource(
                camera.camera_id,
                camera.usb_index,
                status_sink=store.save_camera_status,
            )
        if camera.rtsp_url is None:
            raise ConfigurationError("RTSP camera URL is missing")
        return RtspVideoSource(
            camera.camera_id,
            camera.rtsp_url.get_secret_value(),
            allowed_lan_cidrs=settings.permissions.allowed_lan_cidrs,
            failure_threshold=settings.realtime.reconnect_failure_threshold,
            reconnect=ExponentialReconnect(
                settings.realtime.reconnect_initial_seconds,
                settings.realtime.reconnect_multiplier,
                settings.realtime.reconnect_max_seconds,
            ),
            status_sink=store.save_camera_status,
        )

    return create


def _configured_inference(
    settings: Settings,
    registry: VisionModelRegistry | None = None,
    vision_service: VisionInspectionService | None = None,
) -> InferenceFunction:
    registry = registry or VisionModelRegistry.from_config(
        settings.vision,
        settings.permissions,
        seed=settings.app.seed,
    )

    def predict(frame: VideoFrame) -> list[Detection]:
        image = DecodedImage(
            path=(
                settings.app.workspace_dir / "cameras" / f"{frame.camera_id}-{frame.sequence}.frame"
            ).resolve(),
            checksum=hashlib.sha256(frame.image.tobytes()).hexdigest(),
            bgr=frame.image,
        )
        if vision_service is not None:
            return vision_service.detect_decoded(
                image,
                temporal_key=f"camera:{frame.camera_id}:scene",
            )
        results: list[list[Detection]] = []
        enabled = registry.enabled()
        for detector in enabled:
            try:
                results.append(detector.predict(image))
            except Exception as exc:
                LOGGER.warning(
                    "Realtime detector %s failed without stopping camera: %s",
                    detector.name,
                    exc,
                )
        threshold = min(
            (detector.config.nms_iou for detector in enabled),
            default=0.5,
        )
        return fuse_detections(results, threshold)

    return predict


def create_camera_manager(
    settings: Settings,
    performance_sink: PerformanceSink | None = None,
    model_registry: VisionModelRegistry | None = None,
    vision_service: VisionInspectionService | None = None,
) -> CameraManager:
    workspace = settings.app.workspace_dir.resolve()
    image_dir = settings.realtime.event_image_dir.resolve()
    clip_dir = settings.realtime.event_clip_dir.resolve()
    for path, label in ((image_dir, "event_image_dir"), (clip_dir, "event_clip_dir")):
        try:
            path.relative_to(workspace)
        except ValueError as exc:
            raise ConfigurationError(f"Realtime {label} must remain inside workspace") from exc
    database = Database(settings.app.database_path)
    database.initialize()
    store = DatabaseRealtimeStore(database)
    writer = ClipWriter(
        image_dir,
        clip_dir,
        codec=settings.realtime.clip_codec,
        fps=settings.realtime.clip_fps,
    )
    event_engine = EventEngine(
        store=store,
        writer=writer,
        severity_by_type=settings.realtime.event_severity,
        cooldown_seconds=settings.realtime.event_cooldown_seconds,
        resolve_seconds=settings.realtime.event_resolve_seconds,
        region_iou_threshold=settings.realtime.event_region_iou_threshold,
        before_seconds=settings.realtime.evidence_before_seconds,
        after_seconds=settings.realtime.evidence_after_seconds,
        save_clips=settings.realtime.save_event_clips,
    )
    return CameraManager(
        settings.realtime,
        store=store,
        event_engine=event_engine,
        inference=_configured_inference(settings, model_registry, vision_service),
        source_factory=_configured_source_factory(settings, store),
        performance_sink=performance_sink,
    )


def register_realtime_tools(
    registry: ToolRegistry,
    manager: CameraManager,
    *,
    timeout_seconds: float = 30,
) -> None:
    def start(raw: object) -> CameraActionOutput:
        request = CameraActionInput.model_validate(raw)
        return CameraActionOutput(status=manager.start(request.camera_id))

    def stop(raw: object) -> CameraActionOutput:
        request = CameraActionInput.model_validate(raw)
        return CameraActionOutput(status=manager.stop(request.camera_id))

    def query_events(raw: object) -> QueryRecentEventsOutput:
        return manager.query_events(QueryRecentEventsInput.model_validate(raw))

    def acknowledge(raw: object) -> EventActionOutput:
        request = EventActionInput.model_validate(raw)
        return manager.acknowledge_event(request.event_id)

    def close(raw: object) -> EventActionOutput:
        request = EventActionInput.model_validate(raw)
        return manager.close_event(request.event_id)

    def statuses(raw: object) -> ListCameraStatusOutput:
        request = ListCameraStatusInput.model_validate(raw)
        return manager.list_status(request.include_stopped)

    definitions = [
        (
            ToolDefinition(
                name="start_camera_monitoring",
                description="Start one configured local camera monitoring pipeline.",
                input_schema=CameraActionInput,
                output_schema=CameraActionOutput,
                permission="confirm",
                read_only=False,
                timeout_seconds=timeout_seconds,
                category="realtime",
            ),
            start,
        ),
        (
            ToolDefinition(
                name="stop_camera_monitoring",
                description="Stop one camera and release its local resources.",
                input_schema=CameraActionInput,
                output_schema=CameraActionOutput,
                permission="confirm",
                read_only=False,
                timeout_seconds=timeout_seconds,
                category="realtime",
            ),
            stop,
        ),
        (
            ToolDefinition(
                name="query_recent_events",
                description="Query recent aggregated realtime risk events.",
                input_schema=QueryRecentEventsInput,
                output_schema=QueryRecentEventsOutput,
                permission="auto",
                read_only=True,
                timeout_seconds=timeout_seconds,
                category="realtime",
            ),
            query_events,
        ),
        (
            ToolDefinition(
                name="acknowledge_event",
                description="Acknowledge one active realtime risk event.",
                input_schema=EventActionInput,
                output_schema=EventActionOutput,
                permission="confirm",
                read_only=False,
                timeout_seconds=timeout_seconds,
                category="realtime",
            ),
            acknowledge,
        ),
        (
            ToolDefinition(
                name="close_event",
                description="Resolve one realtime risk event and save ending evidence.",
                input_schema=EventActionInput,
                output_schema=EventActionOutput,
                permission="confirm",
                read_only=False,
                timeout_seconds=timeout_seconds,
                category="realtime",
            ),
            close,
        ),
        (
            ToolDefinition(
                name="list_camera_status",
                description="List current persisted camera states.",
                input_schema=ListCameraStatusInput,
                output_schema=ListCameraStatusOutput,
                permission="auto",
                read_only=True,
                timeout_seconds=timeout_seconds,
                category="realtime",
            ),
            statuses,
        ),
    ]
    for definition, handler in definitions:
        registry.register(definition, handler)
