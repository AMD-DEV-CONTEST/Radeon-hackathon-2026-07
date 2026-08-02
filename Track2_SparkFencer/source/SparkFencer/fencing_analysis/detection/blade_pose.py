"""YOLO-Pose blade detector trained by SparkFencer Blade Pose Studio.

The model predicts one ``blade`` instance with two keypoints: guard and tip.
Predictions are assigned to a fencer through the pose-derived weapon wrist,
then sent through the same confidence-adaptive smoother used by the CV and
box-YOLO detectors.
"""

import numpy as np

from .pose import L_ELBOW, L_WRIST, R_ELBOW, R_WRIST
from .smoothing import make_smoother

KP_CONF_THRESHOLD = 0.3
GUARD_WRIST_GATE_RATIO = 0.12
MIN_FORWARD_FOREARM_RATIO = 0.75


class PoseBladeDetector:
    """Drop-in ``BladeTracker`` replacement for a two-keypoint YOLO-Pose model."""

    def __init__(self, model_path, conf=0.15, device="auto", miss_limit=8, imgsz=1280,
                 smoother="kalman", ema_alpha=0.45):
        from ultralytics import YOLO

        self.sides = ("left", "right")
        self.conf, self.imgsz, self.miss_limit = conf, imgsz, miss_limit
        if device in (None, "auto"):
            try:
                import torch
                device = 0 if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        self.device = device
        print(f"Initializing blade-pose model ({model_path}, device: {device})")
        self.model = YOLO(model_path)
        self.smoothers = {side: make_smoother(smoother, ema_alpha=ema_alpha) for side in self.sides}
        self.miss_count = {side: 0 for side in self.sides}

    def reset(self):
        for smoother in self.smoothers.values():
            smoother.reset()
        self.miss_count = {side: 0 for side in self.sides}

    @staticmethod
    def _weapon_arm(record, side):
        keypoints = np.asarray(record["keypoints"])
        raw_scores = record.get("kp_scores")
        scores = np.asarray(raw_scores) if raw_scores is not None else np.ones(len(keypoints))
        arms = []
        for wrist_i, elbow_i in ((L_WRIST, L_ELBOW), (R_WRIST, R_ELBOW)):
            if scores[wrist_i] < KP_CONF_THRESHOLD or scores[elbow_i] < KP_CONF_THRESHOLD:
                continue
            wrist, elbow = keypoints[wrist_i], keypoints[elbow_i]
            direction = wrist - elbow
            length = float(np.linalg.norm(direction))
            if length > 5 and not np.allclose(wrist, 0):
                arms.append((wrist, direction / length, length))
        if not arms:
            return None, None, None
        if len(arms) == 2:
            arms.sort(key=lambda item: item[0][0], reverse=(side == "left"))
        return arms[0]

    def _predictions(self, frame_bgr):
        result = self.model(frame_bgr, conf=self.conf, imgsz=self.imgsz, device=self.device, verbose=False)[0]
        if result.boxes is None or result.keypoints is None or len(result.boxes) == 0:
            return []
        keypoints = result.keypoints.xy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()
        return [(points[0], points[1], float(scores[index])) for index, points in enumerate(keypoints)
                if len(points) >= 2 and np.all(points >= 0)]

    def update(self, frame_bgr, fencer_records):
        results = {side: {"tip_image": None, "confidence": 0.0} for side in self.sides}
        candidates = self._predictions(frame_bgr)
        claimed = set()
        width = frame_bgr.shape[1]
        for side in self.sides:
            record = fencer_records.get(side)
            if record is None:
                self.miss_count[side] += 1
                continue
            wrist, direction, forearm_len = self._weapon_arm(record, side)
            if wrist is None:
                self.miss_count[side] += 1
                continue
            best_index, best_score = None, -1.0
            for index, (guard, tip, model_score) in enumerate(candidates):
                if index in claimed:
                    continue
                guard_dist = float(np.linalg.norm(guard - wrist))
                if guard_dist > width * GUARD_WRIST_GATE_RATIO:
                    continue
                forward = float(np.dot(tip - wrist, direction))
                if forward < forearm_len * MIN_FORWARD_FOREARM_RATIO:
                    continue
                # Prefer high model confidence and a guard that genuinely
                # belongs to this hand; this prevents cross-fencer swaps.
                score = model_score * (1.0 - guard_dist / max(width * GUARD_WRIST_GATE_RATIO, 1.0))
                if score > best_score:
                    best_index, best_score = index, score
            if best_index is not None:
                claimed.add(best_index)
                _guard, tip, model_score = candidates[best_index]
                smoothed = self.smoothers[side].update(tip, confidence=model_score)
                self.miss_count[side] = 0
                results[side] = {
                    "tip_image": [float(smoothed[0]), float(smoothed[1])],
                    "tip_raw_image": [float(tip[0]), float(tip[1])],
                    "confidence": round(model_score, 3),
                }
            else:
                self.miss_count[side] += 1
                if self.miss_count[side] <= self.miss_limit:
                    predicted = self.smoothers[side].update(None)
                    if predicted is not None:
                        results[side] = {"tip_image": [float(predicted[0]), float(predicted[1])], "confidence": 0.1}
        return results
