"""Model-independent IoU tracker."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field

from buildguard.realtime.schemas import TrackedDetection
from buildguard.schemas.common import BoundingBox
from buildguard.schemas.vision import Detection


class Tracker(ABC):
    @abstractmethod
    def update(self, detections: list[Detection], frame_index: int) -> list[TrackedDetection]:
        """Update tracks and return one observation per current detection."""

    @abstractmethod
    def reset(self) -> None:
        """Remove all active track state."""


@dataclass
class _Track:
    track_id: str
    detection: Detection
    hits: int
    age: int
    missed: int
    last_frame: int


class SimpleIoUTracker(Tracker):
    def __init__(
        self,
        *,
        iou_threshold: float,
        max_age: int,
        minimum_hits: int,
    ) -> None:
        if not 0 < iou_threshold <= 1:
            raise ValueError("Tracker IoU threshold must be within (0, 1]")
        if max_age < 0 or minimum_hits < 1:
            raise ValueError("Tracker age/hit limits are invalid")
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.minimum_hits = minimum_hits
        self._tracks: dict[str, _Track] = {}
        self._next_id = 1

    def _new_track(self, detection: Detection, frame_index: int) -> _Track:
        track = _Track(
            track_id=f"track-{self._next_id:06d}",
            detection=detection,
            hits=1,
            age=0,
            missed=0,
            last_frame=frame_index,
        )
        self._next_id += 1
        self._tracks[track.track_id] = track
        return track

    def update(self, detections: list[Detection], frame_index: int) -> list[TrackedDetection]:
        if frame_index < 0:
            raise ValueError("frame_index must be non-negative")
        for track in self._tracks.values():
            track.age += 1
            track.missed += 1
        pairs: list[tuple[float, str, int]] = []
        for track_id, track in self._tracks.items():
            for index, detection in enumerate(detections):
                if track.detection.label != detection.label:
                    continue
                score = track.detection.bounding_box.iou(detection.bounding_box)
                if score >= self.iou_threshold:
                    pairs.append((score, track_id, index))
        pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
        matched_tracks: set[str] = set()
        matched_detections: set[int] = set()
        assignments: dict[int, _Track] = {}
        for _, track_id, detection_index in pairs:
            if track_id in matched_tracks or detection_index in matched_detections:
                continue
            track = self._tracks[track_id]
            track.detection = detections[detection_index]
            track.hits += 1
            track.missed = 0
            track.last_frame = frame_index
            matched_tracks.add(track_id)
            matched_detections.add(detection_index)
            assignments[detection_index] = track
        for index, detection in enumerate(detections):
            if index not in assignments:
                assignments[index] = self._new_track(detection, frame_index)
        expired = [
            track_id for track_id, track in self._tracks.items() if track.missed > self.max_age
        ]
        for track_id in expired:
            del self._tracks[track_id]
        return [
            TrackedDetection(
                track_id=assignments[index].track_id,
                detection=detection,
                hits=assignments[index].hits,
                age=assignments[index].age,
                confirmed=assignments[index].hits >= self.minimum_hits,
            )
            for index, detection in enumerate(detections)
        ]

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1


@dataclass
class _ByteTrack:
    track_id: str
    detection: Detection
    hits: int
    age: int
    missed: int
    last_frame: int
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    observations: deque[tuple[int, float, float]] = field(
        default_factory=lambda: deque(maxlen=8)
    )


class ByteTrackTracker(Tracker):
    """Dependency-free two-stage ByteTrack-style online tracker.

    High-confidence observations create tracks. Low-confidence observations
    may recover an existing track in the second association pass, but never
    create a new identity. A constant-velocity prediction reduces identity
    churn during short detector confidence drops.
    """

    def __init__(
        self,
        *,
        iou_threshold: float,
        high_confidence: float,
        low_confidence: float,
        max_age: int,
        minimum_hits: int,
    ) -> None:
        if not 0 < iou_threshold <= 1:
            raise ValueError("Tracker IoU threshold must be within (0, 1]")
        if not 0 <= low_confidence <= high_confidence <= 1:
            raise ValueError("ByteTrack confidence thresholds are invalid")
        if max_age < 0 or minimum_hits < 1:
            raise ValueError("Tracker age/hit limits are invalid")
        self.iou_threshold = iou_threshold
        self.high_confidence = high_confidence
        self.low_confidence = low_confidence
        self.max_age = max_age
        self.minimum_hits = minimum_hits
        self._tracks: dict[str, _ByteTrack] = {}
        self._next_id = 1

    def _new_track(self, detection: Detection, frame_index: int) -> _ByteTrack:
        center_x, center_y = self._center(detection.bounding_box)
        track = _ByteTrack(
            track_id=f"track-{self._next_id:06d}",
            detection=detection,
            hits=1,
            age=0,
            missed=0,
            last_frame=frame_index,
            observations=deque([(frame_index, center_x, center_y)], maxlen=8),
        )
        self._next_id += 1
        self._tracks[track.track_id] = track
        return track

    @staticmethod
    def _center(box: BoundingBox) -> tuple[float, float]:
        return ((box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2)

    def _predicted_box(self, track: _ByteTrack, frame_index: int) -> BoundingBox:
        elapsed = max(1, frame_index - track.last_frame)
        box = track.detection.bounding_box
        dx = track.velocity_x * elapsed
        dy = track.velocity_y * elapsed
        width = box.width
        height = box.height
        x1 = max(0.0, box.x1 + dx)
        y1 = max(0.0, box.y1 + dy)
        return BoundingBox(x1=x1, y1=y1, x2=x1 + width, y2=y1 + height)

    def _associate(
        self,
        track_ids: list[str],
        detection_indices: list[int],
        detections: list[Detection],
        frame_index: int,
    ) -> tuple[dict[int, _ByteTrack], set[str]]:
        pairs: list[tuple[float, str, int]] = []
        for track_id in track_ids:
            track = self._tracks[track_id]
            predicted = self._predicted_box(track, frame_index)
            for index in detection_indices:
                detection = detections[index]
                if track.detection.label != detection.label:
                    continue
                score = predicted.iou(detection.bounding_box)
                if score >= self.iou_threshold:
                    pairs.append((score, track_id, index))
        pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
        assignments: dict[int, _ByteTrack] = {}
        matched_tracks: set[str] = set()
        for _, track_id, detection_index in pairs:
            if track_id in matched_tracks or detection_index in assignments:
                continue
            track = self._tracks[track_id]
            previous_center = self._center(track.detection.bounding_box)
            next_center = self._center(detections[detection_index].bounding_box)
            elapsed = max(1, frame_index - track.last_frame)
            track.velocity_x = (next_center[0] - previous_center[0]) / elapsed
            track.velocity_y = (next_center[1] - previous_center[1]) / elapsed
            track.detection = detections[detection_index]
            track.hits += 1
            track.missed = 0
            track.last_frame = frame_index
            track.observations.append((frame_index, next_center[0], next_center[1]))
            assignments[detection_index] = track
            matched_tracks.add(track_id)
        return assignments, matched_tracks

    def update(
        self,
        detections: list[Detection],
        frame_index: int,
    ) -> list[TrackedDetection]:
        if frame_index < 0:
            raise ValueError("frame_index must be non-negative")
        for track in self._tracks.values():
            track.age += 1
            track.missed += 1

        high = [
            index
            for index, detection in enumerate(detections)
            if detection.confidence >= self.high_confidence
        ]
        low = [
            index
            for index, detection in enumerate(detections)
            if self.low_confidence <= detection.confidence < self.high_confidence
        ]
        available_tracks = sorted(self._tracks)
        assignments, matched = self._associate(available_tracks, high, detections, frame_index)
        unmatched_tracks = [track_id for track_id in available_tracks if track_id not in matched]
        recovered, _ = self._associate(unmatched_tracks, low, detections, frame_index)
        assignments.update(recovered)

        for index in high:
            if index not in assignments:
                assignments[index] = self._new_track(detections[index], frame_index)

        expired = [
            track_id for track_id, track in self._tracks.items() if track.missed > self.max_age
        ]
        for track_id in expired:
            del self._tracks[track_id]

        return [
            TrackedDetection(
                track_id=track.track_id,
                detection=detections[index],
                hits=track.hits,
                age=track.age,
                confirmed=track.hits >= self.minimum_hits,
            )
            for index, track in sorted(assignments.items())
        ]

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1


def _minimum_cost_assignment(costs: list[list[float]]) -> list[tuple[int, int]]:
    """Return a deterministic globally minimal assignment without new dependencies."""
    if not costs or not costs[0]:
        return []
    rows = len(costs)
    columns = len(costs[0])
    size = max(rows, columns)
    invalid = 1_000_000.0
    matrix = [
        [
            costs[row][column]
            if row < rows and column < columns
            else invalid
            for column in range(size)
        ]
        for row in range(size)
    ]
    potentials_row = [0.0] * (size + 1)
    potentials_column = [0.0] * (size + 1)
    matching = [0] * (size + 1)
    previous = [0] * (size + 1)
    for row in range(1, size + 1):
        matching[0] = row
        minimum = [math.inf] * (size + 1)
        used = [False] * (size + 1)
        column = 0
        while True:
            used[column] = True
            current_row = matching[column]
            delta = math.inf
            next_column = 0
            for candidate in range(1, size + 1):
                if used[candidate]:
                    continue
                reduced = (
                    matrix[current_row - 1][candidate - 1]
                    - potentials_row[current_row]
                    - potentials_column[candidate]
                )
                if reduced < minimum[candidate]:
                    minimum[candidate] = reduced
                    previous[candidate] = column
                if minimum[candidate] < delta:
                    delta = minimum[candidate]
                    next_column = candidate
            for candidate in range(size + 1):
                if used[candidate]:
                    potentials_row[matching[candidate]] += delta
                    potentials_column[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            column = next_column
            if matching[column] == 0:
                break
        while True:
            next_column = previous[column]
            matching[column] = matching[next_column]
            column = next_column
            if column == 0:
                break
    assignments = []
    for column in range(1, size + 1):
        row = matching[column]
        if row <= rows and column <= columns:
            assignments.append((row - 1, column - 1))
    return sorted(assignments)


class ObservationCentricByteTrackTracker(ByteTrackTracker):
    """ByteTrack-style association with observation-centric direction recovery."""

    def __init__(
        self,
        *,
        iou_threshold: float,
        high_confidence: float,
        low_confidence: float,
        max_age: int,
        minimum_hits: int,
        direction_cost_weight: float = 0.25,
    ) -> None:
        if not 0 <= direction_cost_weight <= 1:
            raise ValueError("direction_cost_weight must be within 0..1")
        super().__init__(
            iou_threshold=iou_threshold,
            high_confidence=high_confidence,
            low_confidence=low_confidence,
            max_age=max_age,
            minimum_hits=minimum_hits,
        )
        self.direction_cost_weight = direction_cost_weight

    @staticmethod
    def _direction_cost(track: _ByteTrack, next_center: tuple[float, float]) -> float:
        if len(track.observations) < 2:
            return 0.0
        _, previous_x, previous_y = track.observations[-2]
        _, current_x, current_y = track.observations[-1]
        observed_x = current_x - previous_x
        observed_y = current_y - previous_y
        candidate_x = next_center[0] - current_x
        candidate_y = next_center[1] - current_y
        observed_norm = math.hypot(observed_x, observed_y)
        candidate_norm = math.hypot(candidate_x, candidate_y)
        if observed_norm <= 1e-9 or candidate_norm <= 1e-9:
            return 0.0
        cosine = (
            observed_x * candidate_x + observed_y * candidate_y
        ) / (observed_norm * candidate_norm)
        return (1.0 - max(-1.0, min(1.0, cosine))) / 2.0

    def _associate(
        self,
        track_ids: list[str],
        detection_indices: list[int],
        detections: list[Detection],
        frame_index: int,
    ) -> tuple[dict[int, _ByteTrack], set[str]]:
        if not track_ids or not detection_indices:
            return {}, set()
        invalid = 1_000_000.0
        costs: list[list[float]] = []
        for track_id in track_ids:
            track = self._tracks[track_id]
            predicted = self._predicted_box(track, frame_index)
            row: list[float] = []
            for detection_index in detection_indices:
                detection = detections[detection_index]
                if track.detection.label != detection.label:
                    row.append(invalid)
                    continue
                overlap = predicted.iou(detection.bounding_box)
                direction = self._direction_cost(
                    track,
                    self._center(detection.bounding_box),
                )
                cost = (1.0 - overlap) + self.direction_cost_weight * direction
                maximum = (1.0 - self.iou_threshold) + self.direction_cost_weight * 0.5
                row.append(cost if cost <= maximum else invalid)
            costs.append(row)
        assignments: dict[int, _ByteTrack] = {}
        matched_tracks: set[str] = set()
        for track_row, detection_column in _minimum_cost_assignment(costs):
            if costs[track_row][detection_column] >= invalid:
                continue
            track_id = track_ids[track_row]
            detection_index = detection_indices[detection_column]
            track = self._tracks[track_id]
            previous_center = self._center(track.detection.bounding_box)
            next_center = self._center(detections[detection_index].bounding_box)
            elapsed = max(1, frame_index - track.last_frame)
            track.velocity_x = (next_center[0] - previous_center[0]) / elapsed
            track.velocity_y = (next_center[1] - previous_center[1]) / elapsed
            track.detection = detections[detection_index]
            track.hits += 1
            track.missed = 0
            track.last_frame = frame_index
            track.observations.append((frame_index, next_center[0], next_center[1]))
            assignments[detection_index] = track
            matched_tracks.add(track_id)
        return assignments, matched_tracks
