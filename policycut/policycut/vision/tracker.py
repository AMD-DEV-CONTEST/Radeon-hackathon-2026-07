"""Track building from keyframe detections + conversion to RedactionEvents.

Greedy association per contract section 10:
- same category, IoU > 0.3 with the track's last box, otherwise center
  distance < 0.15;
- a temporal gap > 1.5s splits the track;
- tracks are extended one detection interval before the first and after
  the last sighting;
- same-category tracks whose boxes overlap with IoU > 0.6 are merged.

Pure-python at import time (stdlib only); RedactionEvent/new_id and SAM2 are
imported lazily inside the functions that need them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

Box = tuple[float, float, float, float]  # x, y, w, h normalized 0..1

IOU_ASSOCIATE = 0.3
CENTER_DIST_ASSOCIATE = 0.15
GAP_SPLIT_S = 1.5
MERGE_IOU = 0.6
LOW_CONFIDENCE = 0.35
_TIME_EPS = 1e-4


def _iou(a: Box, b: Box) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    iw = min(ax2, bx2) - max(ax1, bx1)
    ih = min(ay2, by2) - max(ay1, by1)
    if iw <= 0.0 or ih <= 0.0:
        return 0.0
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0.0 else 0.0


def _center_distance(a: Box, b: Box) -> float:
    acx, acy = a[0] + a[2] / 2.0, a[1] + a[3] / 2.0
    bcx, bcy = b[0] + b[2] / 2.0, b[1] + b[3] / 2.0
    return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5


def _new_track_id() -> str:
    try:
        from policycut.core.ids import new_track_id
        return new_track_id()
    except Exception:
        import uuid
        return "t_" + uuid.uuid4().hex[:10]


def _new_event_id() -> str:
    try:
        from policycut.core.ids import new_event_id
        return new_event_id()
    except Exception:
        import uuid
        return "e_" + uuid.uuid4().hex[:10]


@dataclass
class Track:
    """A tracked visual object: sorted (t, box) keyframes."""

    id: str
    category: str
    keyframes: list[tuple[float, Box]] = field(default_factory=list)
    score_min: float = 1.0
    warnings: list[str] = field(default_factory=list)

    @property
    def start_s(self) -> float:
        return self.keyframes[0][0] if self.keyframes else 0.0

    @property
    def end_s(self) -> float:
        return self.keyframes[-1][0] if self.keyframes else 0.0

    def box_at(self, t: float) -> Box:
        """Linearly interpolated box at time t (clamped to track range)."""
        kfs = self.keyframes
        if not kfs:
            return (0.0, 0.0, 0.0, 0.0)
        if t <= kfs[0][0]:
            return kfs[0][1]
        if t >= kfs[-1][0]:
            return kfs[-1][1]
        for i in range(1, len(kfs)):
            t0, b0 = kfs[i - 1]
            t1, b1 = kfs[i]
            if t <= t1:
                if t1 - t0 <= _TIME_EPS:
                    return b1
                alpha = (t - t0) / (t1 - t0)
                return tuple(b0[k] + alpha * (b1[k] - b0[k]) for k in range(4))  # type: ignore
        return kfs[-1][1]


def _group_by_timestamp(detections: list) -> list[tuple[float, list]]:
    """Group time-sorted detections into (t, [detections at t]) buckets."""
    groups: list[tuple[float, list]] = []
    for det in detections:
        if groups and abs(det.t - groups[-1][0]) <= _TIME_EPS:
            groups[-1][1].append(det)
        else:
            groups.append((det.t, [det]))
    return groups


def _associate(category: str, dets: list) -> list[Track]:
    """Greedy time-ordered association for a single category."""
    dets = sorted(dets, key=lambda d: (d.t, -d.score))
    finished: list[Track] = []
    active: list[Track] = []
    for t, group in _group_by_timestamp(dets):
        # Retire tracks whose gap exceeds the split threshold.
        still_active: list[Track] = []
        for track in active:
            if t - track.keyframes[-1][0] > GAP_SPLIT_S:
                finished.append(track)
            else:
                still_active.append(track)
        active = still_active

        # Score all candidate (track, detection) pairs.
        candidates: list[tuple[float, int, int]] = []  # (quality, det_idx, track_idx)
        for di, det in enumerate(group):
            for ti, track in enumerate(active):
                last_box = track.keyframes[-1][1]
                iou = _iou(last_box, det.box)
                if iou > IOU_ASSOCIATE:
                    quality = iou
                else:
                    dist = _center_distance(last_box, det.box)
                    if dist >= CENTER_DIST_ASSOCIATE:
                        continue
                    # Rank all center-distance matches below any IoU match.
                    quality = IOU_ASSOCIATE * (1.0 - dist / CENTER_DIST_ASSOCIATE)
                candidates.append((quality, di, ti))
        candidates.sort(key=lambda c: c[0], reverse=True)

        used_dets: set[int] = set()
        used_tracks: set[int] = set()
        for quality, di, ti in candidates:
            if di in used_dets or ti in used_tracks:
                continue
            used_dets.add(di)
            used_tracks.add(ti)
            det = group[di]
            track = active[ti]
            track.keyframes.append((det.t, det.box))
            track.score_min = min(track.score_min, det.score)

        for di, det in enumerate(group):
            if di in used_dets:
                continue
            active.append(
                Track(
                    id=_new_track_id(),
                    category=category,
                    keyframes=[(det.t, det.box)],
                    score_min=det.score,
                )
            )
    finished.extend(active)
    return finished


def _overlap_iou(a: Track, b: Track) -> float:
    """Mean IoU of interpolated boxes over the temporal overlap (0 if none)."""
    start = max(a.start_s, b.start_s)
    end = min(a.end_s, b.end_s)
    if end < start - _TIME_EPS:
        return 0.0
    samples = 5
    if end - start <= _TIME_EPS:
        times = [start]
    else:
        times = [start + (end - start) * i / (samples - 1) for i in range(samples)]
    total = sum(_iou(a.box_at(t), b.box_at(t)) for t in times)
    return total / len(times)


def _merge_pair(a: Track, b: Track) -> Track:
    """Merge b into a (a keeps its id); keyframes at ~same time are averaged."""
    combined = sorted(a.keyframes + b.keyframes, key=lambda kf: kf[0])
    keyframes: list[tuple[float, Box]] = []
    for t, box in combined:
        if keyframes and abs(t - keyframes[-1][0]) <= _TIME_EPS:
            prev_t, prev_box = keyframes[-1]
            avg = tuple((prev_box[k] + box[k]) / 2.0 for k in range(4))
            keyframes[-1] = (prev_t, avg)  # type: ignore
        else:
            keyframes.append((t, box))
    warnings = list(a.warnings)
    for w in b.warnings:
        if w not in warnings:
            warnings.append(w)
    return Track(
        id=a.id if a.start_s <= b.start_s else b.id,
        category=a.category,
        keyframes=keyframes,
        score_min=min(a.score_min, b.score_min),
        warnings=warnings,
    )


def build_tracks(detections: list, duration_s: float, fps: float, settings: Any) -> list[Track]:
    """Build tracks from keyframe detections (see module docstring)."""
    if not detections:
        return []

    by_category: dict[str, list] = {}
    for det in detections:
        by_category.setdefault(det.category, []).append(det)

    tracks: list[Track] = []
    for category, dets in by_category.items():
        tracks.extend(_associate(category, dets))

    # Extend one detection interval before/after the sightings (contract §10).
    interval = float(getattr(settings, "dino_interval_s", 0.5))

    def _snap(t: float) -> float:
        if fps and fps > 0:
            return round(round(t * fps) / fps, 4)
        return round(t, 4)

    for track in tracks:
        if not track.keyframes:
            continue
        t_first, box_first = track.keyframes[0]
        t_last, box_last = track.keyframes[-1]
        lead = _snap(max(0.0, t_first - interval))
        if lead < t_first - _TIME_EPS:
            track.keyframes.insert(0, (lead, box_first))
        tail = _snap(min(max(duration_s, 0.0), t_last + interval))
        if tail > t_last + _TIME_EPS:
            track.keyframes.append((tail, box_last))

    # Merge same-category tracks that overlap spatially (IoU > 0.6).
    merged = True
    while merged:
        merged = False
        for i in range(len(tracks)):
            for j in range(i + 1, len(tracks)):
                a, b = tracks[i], tracks[j]
                if a.category != b.category:
                    continue
                if _overlap_iou(a, b) > MERGE_IOU:
                    tracks[i] = _merge_pair(a, b)
                    tracks.pop(j)
                    merged = True
                    break
            if merged:
                break

    tracks.sort(key=lambda tr: (tr.start_s, tr.category))
    logger.info("build_tracks: %d detections -> %d tracks", len(detections), len(tracks))
    return tracks


def _action_for_category(policy: Any, category: str) -> dict:
    targets = getattr(policy, "visual_targets", None)
    if targets is None and isinstance(policy, dict):
        targets = policy.get("visual_targets")
    for target in targets or []:
        if isinstance(target, dict):
            t_cat = target.get("category")
            action = target.get("action")
        else:
            t_cat = getattr(target, "category", None)
            action = getattr(target, "action", None)
        if t_cat != category:
            continue
        if action is None:
            break
        if hasattr(action, "model_dump"):
            return dict(action.model_dump())
        if isinstance(action, dict):
            return dict(action)
        return {
            "type": getattr(action, "type", "pixelate"),
            "strength": getattr(action, "strength", 65),
        }
    return {"type": "pixelate", "strength": 65}


def tracks_to_events(tracks: list[Track], policy: Any) -> list:
    """Convert tracks to visual RedactionEvents (action from matching target)."""
    from policycut.core.models import BoxKeyframe, RedactionEvent

    events = []
    for track in tracks:
        if not track.keyframes:
            continue
        warnings = list(track.warnings)
        if track.score_min < LOW_CONFIDENCE and "low_confidence" not in warnings:
            warnings.append("low_confidence")
        boxes = [
            BoxKeyframe(
                t=round(t, 4),
                x=round(box[0], 5),
                y=round(box[1], 5),
                w=round(box[2], 5),
                h=round(box[3], 5),
            )
            for t, box in track.keyframes
        ]
        events.append(
            RedactionEvent(
                id=_new_event_id(),
                kind="visual",
                category=track.category,
                status="pending",
                source="auto",
                start_s=round(track.start_s, 4),
                end_s=round(track.end_s, 4),
                action=_action_for_category(policy, track.category),
                confidence=round(min(max(track.score_min, 0.0), 1.0), 4),
                track_id=track.id,
                boxes=boxes,
                warnings=warnings,
            )
        )
    return events


def refine_with_sam2(tracks: list[Track], proxy_path, settings,
                     progress_cb: Optional[Callable] = None) -> dict:
    """Refine tracks with SAM2 mask propagation.

    Returns {track_id: {frame_idx: bool mask}}. Any failure (missing sam2,
    no GPU, video decode issue) returns {} and tags the affected tracks with
    a "rect_fallback" warning so rendering uses interpolated boxes instead.
    """
    if not tracks:
        return {}
    result: dict = {}
    try:
        from policycut.vision import sam2_tracker
        result = sam2_tracker.propagate_tracks(tracks, proxy_path, settings, progress_cb)
        if not isinstance(result, dict):
            result = {}
    except Exception as exc:
        if getattr(settings, "require_rocm", False) and isinstance(exc, RuntimeError):
            raise
        logger.warning("SAM2 refinement unavailable, using rectangle fallback: %s", exc)
        result = {}

    for track in tracks:
        masks = result.get(track.id)
        if not masks:
            result.pop(track.id, None)
            if "rect_fallback" not in track.warnings:
                track.warnings.append("rect_fallback")
    return result
