"""Person/head/helmet/vest association and temporal missing-PPE events."""

from __future__ import annotations

from buildguard.config import (
    PPEEventConfig,
    RealtimeOptimizationConfig,
    TemporalRuleConfig,
)
from buildguard.realtime.schemas import EventCandidate, TrackedDetection, VideoFrame
from buildguard.realtime.temporal_confirmation import MOfNConfirmation
from buildguard.realtime.tracker import (
    ByteTrackTracker,
    ObservationCentricByteTrackTracker,
    SimpleIoUTracker,
    Tracker,
)
from buildguard.schemas.common import BoundingBox
from buildguard.schemas.vision import Detection


def _coverage(container: BoundingBox, child: BoundingBox) -> float:
    x1 = max(container.x1, child.x1)
    y1 = max(container.y1, child.y1)
    x2 = min(container.x2, child.x2)
    y2 = min(container.y2, child.y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersection = (x2 - x1) * (y2 - y1)
    child_area = (child.x2 - child.x1) * (child.y2 - child.y1)
    return intersection / child_area if child_area > 0 else 0.0


def _associate(
    parents: list[tuple[str, Detection]],
    children: list[Detection],
    threshold: float,
) -> dict[str, Detection]:
    candidates = [
        (_coverage(parent.bounding_box, child.bounding_box), parent_id, index)
        for parent_id, parent in parents
        for index, child in enumerate(children)
        if _coverage(parent.bounding_box, child.bounding_box) >= threshold
    ]
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    assigned_parents: set[str] = set()
    assigned_children: set[int] = set()
    result: dict[str, Detection] = {}
    for _, parent_id, child_index in candidates:
        if parent_id in assigned_parents or child_index in assigned_children:
            continue
        result[parent_id] = children[child_index]
        assigned_parents.add(parent_id)
        assigned_children.add(child_index)
    return result


class PPEEventDetector:
    """Track people and require explicit, temporally stable missing-PPE evidence."""

    def __init__(
        self,
        config: PPEEventConfig,
        *,
        tracker_iou_threshold: float = 0.3,
        tracker_min_hits: int = 1,
        tracker_algorithm: str = "simple_iou",
        optimization: RealtimeOptimizationConfig | None = None,
    ) -> None:
        self.config = config
        self.optimization = optimization or RealtimeOptimizationConfig()
        self.tracker: Tracker
        if tracker_algorithm == "oc_bytetrack":
            self.tracker = ObservationCentricByteTrackTracker(
                iou_threshold=tracker_iou_threshold,
                high_confidence=config.person_confidence,
                low_confidence=min(0.1, config.person_confidence),
                max_age=config.track_max_age,
                minimum_hits=tracker_min_hits,
                direction_cost_weight=self.optimization.direction_cost_weight,
            )
        elif tracker_algorithm == "bytetrack":
            self.tracker = ByteTrackTracker(
                iou_threshold=tracker_iou_threshold,
                high_confidence=config.person_confidence,
                low_confidence=min(0.1, config.person_confidence),
                max_age=config.track_max_age,
                minimum_hits=tracker_min_hits,
            )
        else:
            self.tracker = SimpleIoUTracker(
                iou_threshold=tracker_iou_threshold,
                max_age=config.track_max_age,
                minimum_hits=tracker_min_hits,
            )
        rules: dict[str, TemporalRuleConfig] = {}
        if config.monitor_missing_helmet:
            rules["missing_helmet"] = TemporalRuleConfig(
                m=config.m,
                n=config.n,
                alpha=config.smoothing_alpha,
            )
        if config.monitor_missing_safety_vest:
            rules["missing_safety_vest"] = TemporalRuleConfig(
                m=config.m,
                n=config.n,
                alpha=config.smoothing_alpha,
            )
        self.confirmation = MOfNConfirmation(
            rules,
            time_evidence_enabled=(
                self.optimization.enabled
                and self.optimization.time_evidence_enabled
            ),
            evidence_window_seconds=self.optimization.evidence_window_seconds,
            evidence_half_life_seconds=(
                self.optimization.evidence_half_life_seconds
            ),
            evidence_min_positive_seconds=(
                self.optimization.evidence_min_positive_seconds
            ),
            evidence_confirm_threshold=(
                self.optimization.evidence_confirm_threshold
            ),
        )

    def process(
        self,
        frame: VideoFrame,
        detections: list[Detection],
        *,
        tracked_persons: list[TrackedDetection] | None = None,
        timestamp_seconds: float | None = None,
    ) -> list[EventCandidate]:
        persons = [
            item
            for item in detections
            if item.label == "person" and item.confidence >= self.config.person_confidence
        ]
        heads = [
            item
            for item in detections
            if item.label == "head" and item.confidence >= self.config.head_confidence
        ]
        helmets = [
            item
            for item in detections
            if item.label == "helmet" and item.confidence >= self.config.helmet_confidence
        ]
        vests = [
            item
            for item in detections
            if item.label == "safety_vest"
            and item.confidence >= self.config.safety_vest_confidence
        ]
        tracked = (
            tracked_persons
            if tracked_persons is not None
            else self.tracker.update(persons, frame.sequence)
        )
        person_pairs = [(item.track_id, item.detection) for item in tracked if item.confirmed]
        heads_by_person = _associate(person_pairs, heads, self.config.person_head_iou)
        head_pairs = sorted(heads_by_person.items())
        helmets_by_person = _associate(head_pairs, helmets, self.config.head_helmet_iou)
        vests_by_person = _associate(person_pairs, vests, self.config.person_vest_iou)
        candidates: list[EventCandidate] = []
        tracked_by_id = {item.track_id: item for item in tracked}
        if self.config.monitor_missing_helmet:
            for track_id, head in head_pairs:
                missing = track_id not in helmets_by_person
                confidence = min(
                    tracked_by_id[track_id].detection.confidence,
                    head.confidence,
                )
                result = self.confirmation.update(
                    "missing_helmet",
                    track_id,
                    detected=missing,
                    confidence=confidence if missing else 0.0,
                    timestamp_seconds=timestamp_seconds,
                )
                should_emit = (
                    result.suspected
                    if self.optimization.enabled
                    else result.confirmed
                )
                if should_emit and missing:
                    person = tracked_by_id[track_id]
                    candidates.append(
                        EventCandidate(
                            camera_id=frame.camera_id,
                            event_type="missing_helmet",
                            track_id=track_id,
                            bbox=person.bbox,
                            confidence=result.smoothed_confidence,
                            confirmed=result.confirmed,
                            frame=frame,
                            detections=[person],
                        )
                    )
        if self.config.monitor_missing_safety_vest:
            for track_id, person_detection in person_pairs:
                missing = track_id not in vests_by_person
                confidence = person_detection.confidence
                result = self.confirmation.update(
                    "missing_safety_vest",
                    track_id,
                    detected=missing,
                    confidence=confidence if missing else 0.0,
                    timestamp_seconds=timestamp_seconds,
                )
                should_emit = (
                    result.suspected
                    if self.optimization.enabled
                    else result.confirmed
                )
                if should_emit and missing:
                    person = tracked_by_id[track_id]
                    candidates.append(
                        EventCandidate(
                            camera_id=frame.camera_id,
                            event_type="missing_safety_vest",
                            track_id=track_id,
                            bbox=person.bbox,
                            confidence=result.smoothed_confidence,
                            confirmed=result.confirmed,
                            frame=frame,
                            detections=[person],
                        )
                    )
        return candidates

    def reset(self) -> None:
        self.tracker.reset()
        self.confirmation.reset()
