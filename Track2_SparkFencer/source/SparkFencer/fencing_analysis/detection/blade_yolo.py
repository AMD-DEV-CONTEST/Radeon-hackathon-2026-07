"""Learned blade-tip detector (fine-tuned YOLO), drop-in replacement for the
CV BladeTracker. Enabled via config.yaml: blade.model_path.

The model is trained on the Roboflow "Fencing Blade" dataset with 3 classes:
  0 blade-guard  — small box at the guard/hand end
  1 blade-tip    — small box at the tip
  2 fencing-blade — box over the whole blade

Per frame: detect all boxes, pair each tip with a guard (prefer pairs enclosed
by the same fencing-blade box, else nearest guard), then assign each pair to
the fencer whose leading wrist is closest to the guard. The tip goes through
the same Kalman smoothing as the CV tracker, and every output carries the
detector confidence — same contract as BladeTracker.update().
"""

import numpy as np

from .pose import L_ELBOW, L_WRIST, R_ELBOW, R_WRIST
from .smoothing import make_smoother

KP_CONF_THRESHOLD = 0.3
GUARD, TIP, BLADE = 0, 1, 2
# Assignment gates as fractions of frame width: the guard sits at the hand, so
# it must be very close to the wrist; a guard-less tip may be a blade-length
# away but never on the opponent's side of the piste.
GUARD_WRIST_GATE = 0.09
TIP_WRIST_GATE = 0.35
# A detection jumping farther than this from the filter state means the filter
# was tracking the wrong blade — re-lock instead of smoothing across.
KALMAN_RELOCK_GATE = 0.13


def _center(box):
    return np.array([(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0])


def _inside(point, box, margin=8):
    return (box[0] - margin <= point[0] <= box[2] + margin
            and box[1] - margin <= point[1] <= box[3] + margin)


class YoloBladeDetector:
    """Same update() contract as BladeTracker, backed by a trained model."""

    def __init__(self, model_path, conf=0.25, device="auto", miss_limit=8, imgsz=1280,
                 smoother="kalman", ema_alpha=0.45):
        from ultralytics import YOLO

        self.sides = ("left", "right")
        self.conf = conf
        # Blade tips vanish when the frame is downscaled — infer at (or near)
        # native resolution. Training used imgsz=1280; on 1080p video 1920
        # noticeably improves recall.
        self.imgsz = imgsz
        self._smoother_kind, self._ema_alpha = smoother, ema_alpha
        if device in (None, "auto"):
            try:
                import torch
                device = 0 if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        self.device = device
        print(f"Initializing YOLO blade model ({model_path}, device: {self.device})")
        self.model = YOLO(model_path)
        self.smoothers = {side: make_smoother(smoother, ema_alpha=ema_alpha)
                          for side in self.sides}
        self.miss_count = {side: 0 for side in self.sides}
        self.miss_limit = miss_limit

    def reset(self):
        for s in self.smoothers.values():
            s.reset()
        self.miss_count = {side: 0 for side in self.sides}

    def _leading_wrist(self, record, side):
        kp = np.asarray(record["keypoints"])
        sc = record.get("kp_scores")
        sc = np.asarray(sc) if sc is not None else np.ones(len(kp))
        arms = []
        for w_i, e_i in ((L_WRIST, L_ELBOW), (R_WRIST, R_ELBOW)):
            if sc[w_i] < KP_CONF_THRESHOLD or np.allclose(kp[w_i], 0):
                continue
            arms.append(kp[w_i])
        if not arms:
            return None
        if len(arms) == 2:
            arms.sort(key=lambda p: p[0], reverse=(side == "left"))
        return arms[0]

    def _detect_pairs(self, frame_bgr):
        """Return [(guard_xy, tip_xy, score)] for every blade in the frame."""
        result = self.model(frame_bgr, conf=self.conf, imgsz=self.imgsz,
                            device=self.device, verbose=False)[0]
        if result.boxes is None or len(result.boxes) == 0:
            return []
        boxes = result.boxes.xyxy.cpu().numpy()
        classes = result.boxes.cls.cpu().numpy().astype(int)
        scores = result.boxes.conf.cpu().numpy()

        # Broadcast graphics live at the bottom of the frame (scoreboards,
        # picture-in-picture replays) and can contain blades — ignore that band.
        max_y = frame_bgr.shape[0] * 0.78
        keep = [(boxes[i][1] + boxes[i][3]) / 2 < max_y for i in range(len(classes))]
        boxes, classes, scores = boxes[keep], classes[keep], scores[keep]

        guards = [(boxes[i], scores[i]) for i in range(len(classes)) if classes[i] == GUARD]
        tips = [(boxes[i], scores[i]) for i in range(len(classes)) if classes[i] == TIP]
        blades = [boxes[i] for i in range(len(classes)) if classes[i] == BLADE]

        pairs = []
        used_guards = set()
        for tip_box, tip_score in sorted(tips, key=lambda t: -t[1]):
            tip_c = _center(tip_box)
            # Prefer the guard sharing a fencing-blade box with this tip.
            container = next((b for b in blades if _inside(tip_c, b)), None)
            best_g, best_d = None, None
            for gi, (guard_box, guard_score) in enumerate(guards):
                if gi in used_guards:
                    continue
                guard_c = _center(guard_box)
                if container is not None and not _inside(guard_c, container):
                    continue
                d = np.linalg.norm(guard_c - tip_c)
                if best_d is None or d < best_d:
                    best_g, best_d = gi, d
            if best_g is None:
                # No guard available; still usable if a blade box orients us.
                if container is not None:
                    pairs.append((None, tip_c, float(tip_score)))
                continue
            used_guards.add(best_g)
            pairs.append((_center(guards[best_g][0]), tip_c, float(tip_score)))
        return pairs

    def _smooth(self, side, tip_c, confidence=1.0):
        """Configured smoothing (kalman/ema/none) — continuous, fluid trails.
        Side ownership is already protected by the pairing gates, so smoothing
        across frames is safe."""
        return self.smoothers[side].update(tip_c, confidence=confidence)

    def update(self, frame_bgr, fencer_records):
        """Return {side: {"tip_image": [x,y]|None, "confidence": float}}."""
        results = {side: {"tip_image": None, "confidence": 0.0} for side in self.sides}
        width = frame_bgr.shape[1]
        guard_gate = GUARD_WRIST_GATE * width
        tip_gate = TIP_WRIST_GATE * width
        pairs = self._detect_pairs(frame_bgr)

        claimed = set()
        for side in self.sides:
            record = fencer_records.get(side)
            if record is None:
                self.miss_count[side] += 1
                continue
            wrist = self._leading_wrist(record, side)
            if wrist is None:
                self.miss_count[side] += 1
                continue

            # Pass 1: guard-anchored pairs (reliable ownership).
            # Pass 2: guard-less tips, gated so we never claim the opponent's.
            best_i, best_d = None, None
            for want_guard in (True, False):
                for i, (guard_c, tip_c, _score) in enumerate(pairs):
                    if i in claimed or (guard_c is not None) != want_guard:
                        continue
                    anchor = guard_c if guard_c is not None else tip_c
                    d = float(np.linalg.norm(anchor - wrist))
                    if d > (guard_gate if want_guard else tip_gate):
                        continue
                    if best_d is None or d < best_d:
                        best_i, best_d = i, d
                if best_i is not None:
                    break

            if best_i is not None:
                claimed.add(best_i)
                _guard_c, tip_c, score = pairs[best_i]
                smoothed = self._smooth(side, tip_c, score)
                self.miss_count[side] = 0
                results[side] = {
                    "tip_image": [float(smoothed[0]), float(smoothed[1])],
                    "confidence": round(score, 3),
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
