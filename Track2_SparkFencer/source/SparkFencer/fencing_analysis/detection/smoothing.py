"""Pluggable tip smoothers, shared by the CV and YOLO blade detectors.

Selected via config blade.filter: kalman | ema | none — exposed in the CLI
(--blade-filter) and WebUI so the options can be compared on the same video.
"""

import cv2
import numpy as np


class KalmanSmoother:
    """Confidence-adaptive constant-velocity Kalman filter.

    A sword tip can move several pixels per frame during an extension, while a
    weak CV line observation is often a piece of the blade, sleeve, or piste.
    The measurement covariance is therefore adjusted on every observation:
    high-confidence geometric matches correct quickly, and marginal matches
    only nudge the trajectory.  ``update`` keeps its optional confidence
    argument so the same smoother remains usable by the YOLO detector.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
        self.kf.transitionMatrix = np.array(
            [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], np.float32
        )
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.35
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 4.0
        self.initialized = False

    def update(self, measurement, confidence=1.0):
        if measurement is None:
            if not self.initialized:
                return None
            predicted = self.kf.predict()
            return np.array([predicted[0, 0], predicted[1, 0]])
        confidence = float(np.clip(confidence, 0.0, 1.0))
        m = np.array([[np.float32(measurement[0])], [np.float32(measurement[1])]])
        if not self.initialized:
            self.kf.statePost = np.array([[m[0, 0]], [m[1, 0]], [0], [0]], np.float32)
            self.initialized = True
            return np.array([m[0, 0], m[1, 0]])
        # 1 px² at confidence 1 (fast response); 25 px² at confidence 0
        # (resists a marginal line candidate).  The process term is raised
        # slightly for strong measurements to accommodate a fast lunge.
        measurement_noise = 1.0 + (1.0 - confidence) ** 2 * 24.0
        process_noise = 0.20 + confidence * 0.55
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * measurement_noise
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * process_noise
        self.kf.predict()
        corrected = self.kf.correct(m)
        return np.array([corrected[0, 0], corrected[1, 0]])


class EmaSmoother:
    """Exponential moving average — lighter smoothing, no velocity model.
    On a miss it holds the last position (no extrapolation)."""

    def __init__(self, alpha=0.45):
        self.alpha = alpha
        self.state = None

    def reset(self):
        self.state = None

    def update(self, measurement, confidence=1.0):
        if measurement is None:
            return self.state.copy() if self.state is not None else None
        m = np.asarray(measurement, dtype=np.float32)
        self.state = m if self.state is None else self.alpha * m + (1 - self.alpha) * self.state
        return self.state.copy()


class NoSmoother:
    """Raw detections, no temporal filtering (baseline for comparison)."""

    def reset(self):
        pass

    def update(self, measurement, confidence=1.0):
        return None if measurement is None else np.asarray(measurement, dtype=np.float32)


def make_smoother(kind="kalman", **kwargs):
    kind = (kind or "kalman").lower()
    if kind == "kalman":
        return KalmanSmoother()
    if kind == "ema":
        return EmaSmoother(alpha=kwargs.get("ema_alpha", 0.45))
    if kind in ("none", "raw"):
        return NoSmoother()
    raise ValueError(f"Unknown blade filter: {kind}")
