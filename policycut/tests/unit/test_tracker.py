"""Tests for the box tracker (policycut/vision/tracker.py).

Contract (CONTRACTS.md section 10): greedy IoU association per category,
gap > 1.5 s splits a track, each track becomes one visual RedactionEvent
carrying the policy action for its category, confidence = min score.
SAM2 must be optional: without it the tracker falls back to box keyframes.

Contract signature: build_tracks(detections, duration_s, fps, settings);
tracks_to_events(tracks, policy).
"""

from __future__ import annotations

import pytest

from policycut.config import Settings
from policycut.core.models import MediaInfo
from policycut.vision import tracker as tracker_mod
from policycut.vision.tracker import build_tracks


# --- flexible Detection construction ----------------------------------------

def make_detection(t: float, category: str, box: tuple[float, float, float, float],
                   score: float, source: str = "dino"):
    """Detection(t, category, box_norm, score, source) per the contract."""
    cls = None
    try:
        from policycut.vision.detector import Detection as cls  # type: ignore
    except Exception:
        cls = getattr(tracker_mod, "Detection", None)
    if cls is not None:
        for attempt in (
            lambda: cls(t=t, category=category, box_norm=box, score=score, source=source),
            lambda: cls(t=t, category=category, box_norm=list(box), score=score, source=source),
            lambda: cls(t, category, box, score, source),
        ):
            try:
                return attempt()
            except Exception:
                continue
    from types import SimpleNamespace

    return SimpleNamespace(t=t, category=category, box_norm=box, score=score, source=source)


def _get(obj, *names, default=None):
    for n in names:
        if isinstance(obj, dict):
            if n in obj:
                return obj[n]
        elif hasattr(obj, n):
            return getattr(obj, n)
    return default


def track_category(tr) -> str:
    return str(_get(tr, "category", default=""))


@pytest.fixture()
def video_info():
    return MediaInfo(
        filename="clip.mp4",
        duration_s=5.0,
        width=640,
        height=360,
        fps=25.0,
        codec="h264",
        has_audio=False,
        size_bytes=1_000_000,
    )


@pytest.fixture()
def settings():
    return Settings()


def run_build_tracks(dets, video_info, settings):
    """Call build_tracks with the contract signature (§1/§10)."""
    return build_tracks(dets, video_info.duration_s, video_info.fps, settings)


def face_seq(ts: list[float], x0: float = 0.10, drift: float = 0.02,
             score: float = 0.9) -> list:
    """A face box drifting slowly right — consecutive IoU stays high."""
    dets = []
    for i, t in enumerate(ts):
        dets.append(make_detection(t, "face", (x0 + i * drift, 0.30, 0.20, 0.30), score))
    return dets


class TestBuildTracks:
    def test_single_moving_object_one_track(self, video_info, settings):
        dets = face_seq([0.0, 0.5, 1.0, 1.5])
        tracks = run_build_tracks(dets, video_info, settings)
        assert len(tracks) == 1
        assert track_category(tracks[0]) == "face"

    def test_gap_splits_track(self, video_info, settings):
        early = face_seq([0.0, 0.5], x0=0.10)
        late = face_seq([2.5, 3.0], x0=0.10)  # 2.0 s gap > 1.5 s
        tracks = run_build_tracks(early + late, video_info, settings)
        assert len(tracks) == 2, f"a 2 s gap must split the track, got {len(tracks)}"

    def test_small_gap_does_not_split(self, video_info, settings):
        dets = face_seq([0.0, 0.5, 1.0]) + face_seq([2.0, 2.5], x0=0.16)  # 1.0 s gap
        tracks = run_build_tracks(dets, video_info, settings)
        assert len(tracks) == 1, "a 1.0 s gap must NOT split the track"

    def test_two_distant_objects_two_tracks(self, video_info, settings):
        left = face_seq([0.0, 0.5, 1.0], x0=0.05)
        right = face_seq([0.0, 0.5, 1.0], x0=0.70)
        tracks = run_build_tracks(left + right, video_info, settings)
        assert len(tracks) == 2

    def test_categories_not_mixed(self, video_info, settings):
        faces = face_seq([0.0, 0.5, 1.0], x0=0.10)
        plates = [
            make_detection(t, "license_plate", (0.11, 0.31, 0.20, 0.30), 0.8)
            for t in (0.0, 0.5, 1.0)
        ]  # same place as the face, different category
        tracks = run_build_tracks(faces + plates, video_info, settings)
        assert len(tracks) == 2
        assert sorted(track_category(t) for t in tracks) == ["face", "license_plate"]

    def test_empty_detections(self, video_info, settings):
        assert run_build_tracks([], video_info, settings) == []


class TestTracksToEvents:
    def _events(self, tracks, sample_policy, video_info):
        fn = getattr(tracker_mod, "tracks_to_events", None)
        assert callable(fn), "tracker module must expose tracks_to_events"
        import inspect

        sig = inspect.signature(fn)
        pool = {
            "tracks": tracks,
            "policy": sample_policy,
            "spec": sample_policy,
            "video_info": video_info,
            "media": video_info,
        }
        kwargs = {}
        for name, param in sig.parameters.items():
            if name in pool:
                kwargs[name] = pool[name]
        return fn(**kwargs)

    def test_one_event_per_track(self, video_info, settings, sample_policy):
        dets = face_seq([0.0, 0.5]) + face_seq([3.0, 3.5], x0=0.5)
        tracks = run_build_tracks(dets, video_info, settings)
        events = self._events(tracks, sample_policy, video_info)
        assert len(events) == len(tracks)

    def test_event_fields_and_policy_action(self, video_info, settings, sample_policy):
        dets = face_seq([0.0, 0.5, 1.0], score=0.9)
        tracks = run_build_tracks(dets, video_info, settings)
        events = self._events(tracks, sample_policy, video_info)
        assert len(events) == 1
        e = events[0]
        assert _get(e, "kind") == "visual"
        assert _get(e, "category") == "face"
        action = _get(e, "action")
        action = action if isinstance(action, dict) else action.__dict__
        # sample_policy: face -> pixelate strength 65
        assert action["type"] == "pixelate"
        assert action.get("strength") == 65
        boxes = _get(e, "boxes", default=[])
        assert len(boxes) >= 2, "event must carry keyframe boxes"
        assert _get(e, "track_id"), "event must reference its track"
        start = float(_get(e, "start_s", "start"))
        end = float(_get(e, "end_s", "end"))
        assert start < end
        assert start <= 0.5 and end >= 1.0  # covers sightings (may extend 1 interval)

    def test_confidence_is_min_score(self, video_info, settings, sample_policy):
        dets = [
            make_detection(0.0, "face", (0.10, 0.30, 0.20, 0.30), 0.90),
            make_detection(0.5, "face", (0.12, 0.30, 0.20, 0.30), 0.62),
            make_detection(1.0, "face", (0.14, 0.30, 0.20, 0.30), 0.85),
        ]
        tracks = run_build_tracks(dets, video_info, settings)
        events = self._events(tracks, sample_policy, video_info)
        assert len(events) == 1
        conf = float(_get(events[0], "confidence", default=1.0))
        assert conf == pytest.approx(0.62, abs=0.05)

    def test_plate_gets_blur_action(self, video_info, settings, sample_policy):
        dets = [
            make_detection(t, "license_plate", (0.4, 0.6, 0.15, 0.08), 0.8)
            for t in (0.0, 0.5, 1.0)
        ]
        tracks = run_build_tracks(dets, video_info, settings)
        events = self._events(tracks, sample_policy, video_info)
        assert len(events) == 1
        action = _get(events[0], "action")
        action = action if isinstance(action, dict) else action.__dict__
        # sample_policy: license_plate -> blur strength 60
        assert action["type"] == "blur"
