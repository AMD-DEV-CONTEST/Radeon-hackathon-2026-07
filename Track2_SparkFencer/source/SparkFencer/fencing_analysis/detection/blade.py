"""Blade tip detection and tracking.

A fencing blade is a thin, fast-moving line segment anchored at the weapon
hand. Detecting it reliably from ordinary video is hard, so this tracker is
deliberately conservative:

  1. Anchor at the fencer's leading wrist, extend a search ROI along the
     forearm direction (elbow -> wrist extrapolated).
  2. Inside the ROI, combine a frame-difference motion mask with a fast line
     segment detector and keep segments roughly collinear with the forearm
     that start near the wrist.
  3. The far endpoint of the best segment is the tip estimate; a Kalman
     filter smooths it and every frame carries a confidence score. Frames
     with no acceptable segment are reported with confidence 0 rather than a
     fabricated position.

A fine-tuned YOLO tip model can replace this by setting blade.model_path in
config.yaml (interface kept identical).
"""

import cv2
import numpy as np

from .pose import L_ELBOW, L_WRIST, R_ELBOW, R_WRIST
from .smoothing import make_smoother

KP_CONF_THRESHOLD = 0.3
# Blade search length as a multiple of the forearm length.
BLADE_REACH_FOREARM_RATIO = 3.5
# Max angle (degrees) between forearm direction and accepted blade segment.
MAX_ANGLE_DEV_DEG = 35.0
# Segment must start within this multiple of forearm length from the wrist.
MAX_ROOT_DIST_RATIO = 1.2
# A segment that ends close to the wrist is normally just a fragmented part of
# the blade (or the guard), not its tip.  Prefer no point over that false tip.
MIN_TIP_DIST_FOREARM_RATIO = 1.15
# Reject weak line matches before they enter the temporal filter.  Kalman can
# smooth noise, but cannot turn a body/background line into a sword tip.
MIN_CV_SCORE = 0.62
# The endpoint must remain in a forward cone projected from the weapon wrist.
# This is deliberately tighter than the segment/forearm angle because a torso
# or piste line may happen to be parallel without being in front of the hand.
MAX_TIP_CONE_DEG = 28.0
# A very large jump from the last observed endpoint is possible in a lunge,
# but deserves a lower score until the pose/line evidence confirms it.
TEMPORAL_REACH_RATIO = 1.75
# The thin, fast, often motion-blurred tip section frequently loses contrast
# and gets detected as its own short fragment, separate from the brighter
# mid-blade segment. Chain in any further segment that continues in (nearly)
# the same direction within this gap/angle tolerance, so the reported tip is
# the true physical endpoint rather than wherever the anchor fragment ended.
CHAIN_GAP_FOREARM_RATIO = 0.55
CHAIN_ANGLE_DEV_DEG = 22.0
CHAIN_PERP_TOLERANCE_RATIO = 0.12
CHAIN_MAX_STEPS = 8


def _make_line_detector():
    try:
        return cv2.ximgproc.createFastLineDetector(
            # Lowered from the OpenCV default (~25px) so the short terminal
            # fragment at the actual blade tip still registers as a
            # detectable line instead of being discarded outright — it gets
            # picked up by the chaining step in _detect_tip, not scored on
            # its own.
            length_threshold=12,
            distance_threshold=1.6,
            do_merge=True,
        )
    except AttributeError:
        return None


class BladeTracker:
    """Per-fencer blade tip tracker. Call update() once per frame."""

    def __init__(self, sides=("left", "right"), miss_limit=8,
                 smoother="kalman", ema_alpha=0.45):
        self.sides = sides
        self.detector = _make_line_detector()
        self._smoother_kind, self._ema_alpha = smoother, ema_alpha
        self.smoothers = {side: make_smoother(smoother, ema_alpha=ema_alpha)
                          for side in sides}
        self.miss_count = {side: 0 for side in sides}
        self.last_raw_tip = {side: None for side in sides}
        self.miss_limit = miss_limit
        self.prev_gray = None
        if self.detector is None:
            print("Warning: cv2.ximgproc unavailable; blade detection disabled "
                  "(install opencv-contrib-python).")

    def _arm_anchor(self, fencer_record, side):
        """Return (wrist, forearm_dir, forearm_len) of the leading arm.

        The weapon arm is the one whose wrist is more advanced toward the
        opponent: for the left fencer that is the larger x, for the right
        fencer the smaller x.
        """
        kp = np.asarray(fencer_record["keypoints"])
        scores = fencer_record.get("kp_scores")
        scores = np.asarray(scores) if scores is not None else np.ones(len(kp))

        arms = []
        for wrist_i, elbow_i in ((L_WRIST, L_ELBOW), (R_WRIST, R_ELBOW)):
            if scores[wrist_i] < KP_CONF_THRESHOLD or scores[elbow_i] < KP_CONF_THRESHOLD:
                continue
            wrist, elbow = kp[wrist_i], kp[elbow_i]
            if np.allclose(wrist, 0) or np.allclose(elbow, 0):
                continue
            arms.append((wrist, elbow))
        if not arms:
            return None, None, None

        if len(arms) == 2:
            arms.sort(key=lambda a: a[0][0], reverse=(side == "left"))
        wrist, elbow = arms[0]
        direction = wrist - elbow
        length = float(np.linalg.norm(direction))
        if length < 5:
            return None, None, None
        return wrist, direction / length, length

    def _detect_tip(self, gray, motion_mask, wrist, direction, forearm_len,
                    previous_tip=None):
        reach = forearm_len * BLADE_REACH_FOREARM_RATIO
        center = wrist + direction * reach / 2.0
        half = reach / 2.0 + forearm_len

        h, w = gray.shape[:2]
        x1 = int(max(0, center[0] - half))
        y1 = int(max(0, center[1] - half))
        x2 = int(min(w - 1, center[0] + half))
        y2 = int(min(h - 1, center[1] + half))
        if x2 - x1 < 20 or y2 - y1 < 20:
            return None, 0.0

        roi = gray[y1:y2, x1:x2]
        # Do not use motion as the only image source: a blade held still for
        # one frame has almost no frame-difference signal.  CLAHE improves
        # the faint, reflective blade in dark broadcast footage; the motion
        # masked pass remains a useful supplemental candidate source.
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(roi)
        line_sets = [self.detector.detect(enhanced)]
        if motion_mask is not None:
            roi_mask = motion_mask[y1:y2, x1:x2]
            moving = cv2.bitwise_and(enhanced, enhanced, mask=roi_mask)
            line_sets.append(self.detector.detect(moving))
        raw_lines = [line for detected in line_sets if detected is not None for line in detected.reshape(-1, 4)]
        if not raw_lines:
            return None, 0.0
        # Frame-coordinate segment pairs, reused both for scoring the anchor
        # segment and for chaining further fragments onto its far end.
        frame_lines = [(np.array([line[0] + x1, line[1] + y1]),
                        np.array([line[2] + x1, line[3] + y1])) for line in raw_lines]

        best_tip, best_root, best_score = None, None, 0.0
        max_root_dist = forearm_len * MAX_ROOT_DIST_RATIO
        cos_limit = np.cos(np.deg2rad(MAX_ANGLE_DEV_DEG))
        tip_cone_tan = np.tan(np.deg2rad(MAX_TIP_CONE_DEG))
        for p1, p2 in frame_lines:
            # Root = endpoint closer to the wrist, tip = the other one.
            d1, d2 = np.linalg.norm(p1 - wrist), np.linalg.norm(p2 - wrist)
            root, tip = (p1, p2) if d1 <= d2 else (p2, p1)
            root_dist = min(d1, d2)
            tip_dist = max(d1, d2)
            if root_dist > max_root_dist:
                continue
            if tip_dist < forearm_len * MIN_TIP_DIST_FOREARM_RATIO:
                continue
            seg = tip - root
            seg_len = np.linalg.norm(seg)
            if seg_len < forearm_len * 0.5:
                continue
            cos_angle = float(np.dot(seg / seg_len, direction))
            if cos_angle < cos_limit:
                continue
            # Pose-constrained endpoint gate.  A valid tip is not merely at
            # the far end of a line: it must sit in front of the hand inside a
            # direction cone from the elbow -> wrist vector.
            tip_relative = tip - wrist
            tip_forward = float(np.dot(tip_relative, direction))
            tip_lateral = float(abs(tip_relative[0] * direction[1]
                                    - tip_relative[1] * direction[0]))
            if tip_forward < forearm_len * MIN_TIP_DIST_FOREARM_RATIO:
                continue
            if tip_forward > reach + forearm_len:
                continue
            max_lateral = forearm_len * 0.35 + tip_forward * tip_cone_tan
            if tip_lateral > max_lateral:
                continue

            # Score: long, well-aligned, rooted at the hand, endpoint inside
            # the pose cone, and temporally plausible.  The temporal term is
            # soft (rather than a hard rejection) so a real fast extension can
            # still re-lock the tracker.
            cone_score = max(0.0, 1.0 - tip_lateral / max(max_lateral, 1.0))
            temporal_score = 1.0
            if previous_tip is not None:
                delta = float(np.linalg.norm(tip - previous_tip))
                temporal_score = float(np.exp(-delta / max(reach * TEMPORAL_REACH_RATIO, 1.0)))
            score = (
                min(seg_len / reach, 1.0) * 0.30
                + cos_angle * 0.25
                + (1.0 - root_dist / max(max_root_dist, 1.0)) * 0.18
                + cone_score * 0.17
                + temporal_score * 0.10
            )
            if score >= MIN_CV_SCORE and score > best_score:
                best_score, best_tip, best_root = score, tip, root

        if best_tip is None:
            return None, 0.0

        # The anchor segment's endpoint is often just where its fragment of
        # the blade happened to end, not the true tip — chain in any further
        # collinear fragments (e.g. the thin, faint terminal section) before
        # returning.
        extended_tip = self._extend_to_farthest_fragment(frame_lines, best_root, best_tip, forearm_len)
        tip_relative = extended_tip - wrist
        tip_forward = float(np.dot(tip_relative, direction))
        tip_lateral = float(abs(tip_relative[0] * direction[1] - tip_relative[1] * direction[0]))
        max_lateral = forearm_len * 0.35 + tip_forward * tip_cone_tan
        # Re-validate against the pose cone: chaining must stay in front of
        # the hand and within the forearm-aligned cone, same as any endpoint.
        if tip_forward <= reach + forearm_len and tip_lateral <= max_lateral:
            best_tip = extended_tip
        return best_tip, float(best_score)

    def _extend_to_farthest_fragment(self, frame_lines, root, tip, forearm_len):
        """Greedily chain further collinear segments onto (root, tip).

        FastLineDetector can split one physical blade into several short
        fragments where the thin, fast-moving tip section loses contrast
        (motion blur, a specular highlight band, low light). The scoring
        loop above only picks the best *anchor* fragment, so its raw
        endpoint can land mid-blade. This walks outward from that endpoint,
        absorbing any other detected segment that continues in nearly the
        same direction within a small gap, until nothing more chains on —
        landing on the true physical tip instead of a fragment edge.
        """
        direction = tip - root
        length = float(np.linalg.norm(direction))
        if length < 1e-3:
            return tip
        direction = direction / length
        gap_limit = forearm_len * CHAIN_GAP_FOREARM_RATIO
        perp_limit = forearm_len * CHAIN_PERP_TOLERANCE_RATIO
        cos_limit = np.cos(np.deg2rad(CHAIN_ANGLE_DEV_DEG))

        current_tip = tip
        current_forward = float(np.dot(current_tip - root, direction))
        for _ in range(CHAIN_MAX_STEPS):
            best_candidate, best_forward = None, current_forward
            for p1, p2 in frame_lines:
                for near, far in ((p1, p2), (p2, p1)):
                    if np.linalg.norm(near - current_tip) > gap_limit:
                        continue
                    seg = far - near
                    seg_len = float(np.linalg.norm(seg))
                    if seg_len < 1e-3:
                        continue
                    if float(np.dot(seg / seg_len, direction)) < cos_limit:
                        continue
                    to_far = far - root
                    forward = float(np.dot(to_far, direction))
                    if forward <= best_forward:
                        continue
                    perp = float(abs(to_far[0] * direction[1] - to_far[1] * direction[0]))
                    if perp > perp_limit + forward * 0.05:
                        continue
                    best_forward, best_candidate = forward, far
            if best_candidate is None:
                break
            current_tip, current_forward = best_candidate, best_forward
        return current_tip

    def reset(self):
        """Drop temporal state after a scene cut."""
        self.prev_gray = None
        for s in self.smoothers.values():
            s.reset()
        self.miss_count = {side: 0 for side in self.sides}
        self.last_raw_tip = {side: None for side in self.sides}

    def update(self, frame_gray, fencer_records):
        """Return {side: {"tip_image": [x, y] | None, "confidence": float}}."""
        results = {side: {"tip_image": None, "confidence": 0.0} for side in self.sides}

        motion_mask = None
        if self.prev_gray is not None and self.prev_gray.shape == frame_gray.shape:
            diff = cv2.absdiff(frame_gray, self.prev_gray)
            _, motion_mask = cv2.threshold(diff, 12, 255, cv2.THRESH_BINARY)
            motion_mask = cv2.dilate(motion_mask, np.ones((5, 5), np.uint8))
        self.prev_gray = frame_gray.copy()

        if self.detector is None:
            return results

        for side in self.sides:
            record = fencer_records.get(side)
            if record is None:
                self.miss_count[side] += 1
                continue
            wrist, direction, forearm_len = self._arm_anchor(record, side)
            if wrist is None:
                self.miss_count[side] += 1
                continue

            tip, confidence = self._detect_tip(
                frame_gray, motion_mask, wrist, direction, forearm_len,
                self.last_raw_tip[side],
            )
            if tip is not None:
                smoothed = self.smoothers[side].update(tip, confidence=confidence)
                self.miss_count[side] = 0
                self.last_raw_tip[side] = tip.copy()
                results[side] = {
                    "tip_image": [float(smoothed[0]), float(smoothed[1])],
                    # Keep the instantaneous line endpoint for rendering and
                    # diagnostics.  The filtered point is still used by the
                    # time-series analysis, but can visibly lag a fast lunge.
                    "tip_raw_image": [float(tip[0]), float(tip[1])],
                    "confidence": round(confidence, 3),
                }
            else:
                self.miss_count[side] += 1
                if self.miss_count[side] <= self.miss_limit:
                    predicted = self.smoothers[side].update(None)
                    if predicted is not None:
                        results[side] = {
                            "tip_image": [float(predicted[0]), float(predicted[1])],
                            "confidence": 0.1,
                        }
        return results
