"""Vision pipeline package.

Modules:
- detector: GroundingDINO + YuNet keyframe detection -> list[Detection]
- tracker:  greedy track building, RedactionEvent conversion, SAM2 refinement entry
- sam2_tracker: optional SAM2 video mask propagation (lazy, guarded)
- masks:    pure numpy/cv2 mask post-processing + npz persistence

All heavy ML dependencies (torch, transformers, sam2) are imported lazily
inside functions; importing this package never requires them.
"""

from policycut.vision.detector import Detection, VisualDetector, run_detection
from policycut.vision.tracker import (
    Track,
    build_tracks,
    refine_with_sam2,
    tracks_to_events,
)

__all__ = [
    "Detection",
    "VisualDetector",
    "run_detection",
    "Track",
    "build_tracks",
    "tracks_to_events",
    "refine_with_sam2",
]
