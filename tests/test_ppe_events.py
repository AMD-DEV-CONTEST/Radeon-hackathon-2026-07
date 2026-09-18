from datetime import UTC, datetime, timedelta

import numpy as np

from buildguard.config import PPEEventConfig
from buildguard.realtime.ppe_events import PPEEventDetector
from buildguard.realtime.schemas import VideoFrame
from buildguard.schemas.common import BoundingBox
from buildguard.schemas.vision import Detection


def _detection(label: str, box: tuple[float, float, float, float]) -> Detection:
    return Detection(
        label=label,
        confidence=0.9,
        bounding_box=BoundingBox(
            x1=box[0], y1=box[1], x2=box[2], y2=box[3]
        ),
        source_model="fixture",
    )


def _frame(sequence: int) -> VideoFrame:
    return VideoFrame(
        camera_id="camera-1",
        sequence=sequence,
        captured_at=datetime(2026, 7, 1, tzinfo=UTC)
        + timedelta(seconds=sequence),
        source_time_seconds=float(sequence),
        image=np.zeros((240, 320, 3), dtype=np.uint8),
    )


PERSON = _detection("person", (20, 10, 120, 220))
HEAD = _detection("head", (45, 20, 90, 70))
HELMET = _detection("helmet", (45, 18, 90, 50))
VEST = _detection("safety_vest", (30, 75, 110, 180))


def _detector() -> PPEEventDetector:
    return PPEEventDetector(
        PPEEventConfig(m=3, n=5, track_max_age=3),
        tracker_min_hits=1,
    )


def test_normal_helmet_and_one_frame_miss_do_not_emit() -> None:
    detector = _detector()
    outputs = []
    for sequence, detections in enumerate(
        [
            [PERSON, HEAD, HELMET],
            [PERSON, HEAD],
            [PERSON, HEAD, HELMET],
            [PERSON, HEAD, HELMET],
        ]
    ):
        outputs.extend(detector.process(_frame(sequence), detections))
    assert outputs == []


def test_sustained_missing_helmet_emits_after_m_of_n() -> None:
    detector = _detector()
    outputs = [
        detector.process(_frame(sequence), [PERSON, HEAD])
        for sequence in range(3)
    ]

    assert outputs[0] == []
    assert outputs[1] == []
    assert len(outputs[2]) == 1
    assert outputs[2][0].event_type == "missing_helmet"
    assert outputs[2][0].track_id == "track-000001"


def test_short_head_occlusion_preserves_track_and_history() -> None:
    detector = _detector()
    assert detector.process(_frame(0), [PERSON, HEAD]) == []
    assert detector.process(_frame(1), [PERSON, HEAD]) == []
    assert detector.process(_frame(2), [PERSON]) == []
    assert detector.process(_frame(3), [PERSON]) == []
    result = detector.process(_frame(4), [PERSON, HEAD])

    assert len(result) == 1
    assert result[0].track_id == "track-000001"


def test_helmet_removed_after_safe_frames_requires_new_confirmation() -> None:
    detector = _detector()
    for sequence in range(3):
        assert detector.process(_frame(sequence), [PERSON, HEAD, HELMET]) == []
    assert detector.process(_frame(3), [PERSON, HEAD]) == []
    assert detector.process(_frame(4), [PERSON, HEAD]) == []
    assert len(detector.process(_frame(5), [PERSON, HEAD])) == 1


def test_multiple_people_get_independent_head_associations() -> None:
    detector = PPEEventDetector(PPEEventConfig(m=1, n=1), tracker_min_hits=1)
    second_person = _detection("person", (170, 10, 290, 220))
    second_head = _detection("head", (205, 20, 250, 70))
    second_helmet = _detection("helmet", (205, 18, 250, 50))
    result = detector.process(
        _frame(0),
        [PERSON, HEAD, second_person, second_head, second_helmet],
    )

    assert len(result) == 1
    assert result[0].bbox == PERSON.bounding_box


def test_sustained_missing_vest_emits_without_missing_helmet() -> None:
    detector = PPEEventDetector(
        PPEEventConfig(
            m=2,
            n=3,
            monitor_missing_helmet=True,
            monitor_missing_safety_vest=True,
        ),
        tracker_min_hits=1,
    )

    first = detector.process(_frame(0), [PERSON, HEAD, HELMET])
    second = detector.process(_frame(1), [PERSON, HEAD, HELMET])

    assert first == []
    assert len(second) == 1
    assert second[0].event_type == "missing_safety_vest"


def test_present_vest_suppresses_missing_vest_event() -> None:
    detector = PPEEventDetector(
        PPEEventConfig(
            m=1,
            n=1,
            monitor_missing_safety_vest=True,
        ),
        tracker_min_hits=1,
    )

    assert detector.process(_frame(0), [PERSON, HEAD, HELMET, VEST]) == []
