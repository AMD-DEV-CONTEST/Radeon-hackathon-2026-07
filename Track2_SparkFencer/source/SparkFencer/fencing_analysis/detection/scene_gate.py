"""Bout-view gate for broadcast footage.

Broadcast fencing video cuts away to closeups, replays and crowd shots. Frames
that are not the main bout view must be skipped, otherwise the tracker sees
phantom motion across cuts (position jumps -> fake lunges / speed spikes) and
the overlay draws piste lines over unrelated shots.

Approach: the piste quad is a fixed image region under a fixed bout camera, so
its color histogram is a stable fingerprint. The reference histogram is locked
in lazily — on the first frame where the pose detector finds two persons
standing on the piste (almost certainly the bout view). Every frame is then
compared by histogram correlation.
"""

import cv2
import numpy as np


class SceneGate:
    def __init__(self, piste_corners, threshold=0.5):
        self.corners = np.array(piste_corners, dtype=np.int32)
        self.threshold = threshold
        self.reference = None
        self._mask = None

    def _piste_hist(self, frame):
        if self._mask is None:
            self._mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.fillPoly(self._mask, [self.corners], 255)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], self._mask, [24, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist

    def lock_reference(self, frame):
        """Call when the current frame is confidently the bout view."""
        self.reference = self._piste_hist(frame)

    def is_bout_view(self, frame):
        """True if this frame looks like the main bout camera. Before the
        reference is locked, every frame is treated as a bout view."""
        if self.reference is None:
            return True
        hist = self._piste_hist(frame)
        score = cv2.compareHist(self.reference, hist, cv2.HISTCMP_CORREL)
        return score >= self.threshold
